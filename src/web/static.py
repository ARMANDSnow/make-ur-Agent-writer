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


USER_STATUS_LABELS = {
    "pending": "等待中",
    "queued": "等待中",
    "running": "处理中",
    "generating": "处理中",
    "succeeded": "已完成",
    "completed": "已完成",
    "ok": "已完成",
    "ready": "可以开始",
    "warn": "需要留意",
    "blocked": "需要补充",
    "failed": "未完成",
    "error": "未完成",
    "retry_error": "未完成",
    "aborted": "已取消",
    "cancelled": "已取消",
    "canceled": "已取消",
    "budget_exceeded": "额度不足",
    "stale": "需要更新",
    "lost": "状态待确认",
}


def user_status_label(status: object) -> str:
    """Return a user-facing status and fail closed for new enum values."""
    return USER_STATUS_LABELS.get(str(status or "").lower(), "状态待确认")


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
    icon = icons.get(status, "•")
    if status == "succeeded":
        return icon + " 已完成"
    return icon + " " + user_status_label(status)


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

:root{
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

  /* iter153 public/novel semantic aliases (Phase A) */
  --ui-page-bg: #FBF7F0;
  --ui-card-bg: #FFFEFB;
  --ui-primary-bg: #E6EFE9;
  --ui-paid-bg: #F8E7D3;
  --ui-danger-bg: #F4DCD2;
  --ui-text: #2A2520;
  --ui-text-muted: #5C544A;
  --ui-brand-text: #2E5343;
  --ui-danger-text: #A8533D;
  --ui-focus-ring: #3F6B5A;

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
  --reading-w: 720px;}

/* ---------- reset ---------- */
*, *::before, *::after{ box-sizing: border-box; }
html, body{ margin: 0; padding: 0; }
body{
  background: var(--bg-paper);
  color: var(--ink-1);
  font-family: var(--font-sans);
  font-size: var(--fs-md);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;}
h1, h2, h3, h4{ font-family: var(--font-serif); margin: 0; font-weight: 600; line-height: 1.3; color: var(--ink-1); }
h1{ font-size: var(--fs-h1); }
h2{ font-size: var(--fs-h2); }
h3{ font-size: var(--fs-xl); }
h4{ font-size: var(--fs-lg); }
p{ margin: 0 0 var(--space-3); }
a{ color: var(--jade); text-decoration: none; border-bottom: 1px solid transparent; transition: border-color .15s ease; }
a:hover{ border-bottom-color: var(--jade); }
code, pre, kbd, samp{ font-family: var(--font-mono); font-size: var(--fs-sm); }
pre{ white-space: pre-wrap; word-break: break-word; }
hr{ border: 0; border-top: 1px solid var(--rule); margin: var(--space-4) 0; }
small{ font-size: var(--fs-xs); color: var(--ink-3); }

.muted{ color: var(--ink-3); }
.subdued{ color: var(--ink-2); }
.eyebrow{
  font-family: var(--font-serif);
  text-transform: none;
  letter-spacing: 0.08em;
  font-size: var(--fs-xs);
  color: var(--jade);
  margin: 0;}
.ornament::before{ content: "✦"; color: var(--jade); margin-right: .35em; }

/* ---------- layout: app shell ---------- */
.app{
  display: grid;
  grid-template-columns: var(--sidebar-w) 1fr;
  min-height: 100vh;}
.app.no-context{ grid-template-columns: 1fr; }

.sidebar{
  background: var(--bg-card);
  border-right: 1px solid var(--rule);
  padding: var(--space-5) var(--space-4);
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-5);}
.sidebar .brand{
  font-family: var(--font-serif);
  font-size: var(--fs-xl);
  color: var(--ink-1);
  display: flex;
  align-items: center;
  gap: .35em;
  border: 0;}
.sidebar .brand:hover{ border-bottom: 0; color: var(--jade); }
.sidebar-section{ display: flex; flex-direction: column; gap: var(--space-1); }
.sidebar-library{ min-height: 0; }
.sidebar-library h4{ display: flex; justify-content: space-between; gap: var(--space-2); }
.sidebar-library h4 span{ font-variant-numeric: tabular-nums; }
.sidebar-library-list{
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  max-height: min(32vh, 280px);
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-right: 2px;}
.sidebar-section h4{
  font-family: var(--font-sans);
  font-size: var(--fs-xs);
  color: var(--ink-3);
  letter-spacing: 0.06em;
  margin-bottom: var(--space-2);
  font-weight: 500;
  padding: 0 var(--space-2);}
.sidebar-item{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-1);
  color: var(--ink-2);
  border: 0;
  font-size: var(--fs-sm);}
.sidebar-item > span{ min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sidebar-item:hover{ background: var(--bg-sunken); color: var(--ink-1); border: 0; }
.sidebar-item.active{
  background: var(--jade-soft);
  color: var(--jade-strong);
  font-weight: 600;}
.sidebar-item .dot{
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--ink-3);
  flex: 0 0 6px;}
.sidebar-item.active .dot{ background: var(--jade); }
.sidebar-item .meta{ font-size: var(--fs-xs); color: var(--ink-3); }
.sidebar-footer{
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  font-size: var(--fs-xs);
  color: var(--ink-3);}
.sidebar-overlay{ display: none; }

.main{
  display: flex;
  flex-direction: column;
  min-width: 0;}
.topbar{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-6);
  border-bottom: 1px solid var(--rule);
  background: var(--bg-paper);
  position: sticky;
  top: 0;
  z-index: 5;}
.topbar .breadcrumb{
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-sm);
  color: var(--ink-2);}
.breadcrumb a{ color: var(--ink-2); border: 0; }
.breadcrumb a:hover{ color: var(--jade); }
.breadcrumb .sep{ color: var(--ink-3); }
.breadcrumb .here{ color: var(--ink-1); font-weight: 600; }
.topbar-actions-wrap{ display: flex; align-items: center; position: relative; }
.topbar-actions{ display: flex; gap: var(--space-2); align-items: center; }

.page{
  padding: var(--space-6);
  max-width: 1280px;
  width: 100%;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-6);}
.page-header{ display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-4); }
.page-header .titles{ display: flex; flex-direction: column; gap: var(--space-1); }
.page-header h1{ font-size: var(--fs-display); }

.section{ display: flex; flex-direction: column; gap: var(--space-4); }
.section-title{ display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-3); }
.section-title h2{ font-size: var(--fs-h2); }
.section-title .hint{ color: var(--ink-3); font-size: var(--fs-sm); }

/* ---------- components ---------- */

/* buttons */
.btn{
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
  transition: background .15s ease, border-color .15s ease, color .15s ease;}
.btn:focus-visible{ outline: 2px solid var(--jade); outline-offset: 2px; }
.btn[disabled], .btn:disabled{ opacity: .5; cursor: not-allowed; }
.btn-primary{
  background: var(--amber);
  color: #fff;
  border-color: var(--amber);}
.btn-primary:hover:not(:disabled){ background: var(--amber-strong); border-color: var(--amber-strong); }
.btn-secondary{
  background: var(--bg-card);
  color: var(--jade-strong);
  border-color: var(--rule-strong);}
.btn-secondary:hover:not(:disabled){ background: var(--jade-soft); border-color: var(--jade); }
.btn-ghost{
  background: transparent;
  color: var(--ink-2);
  border-color: transparent;}
.btn-ghost:hover:not(:disabled){ background: var(--bg-sunken); color: var(--ink-1); }
.btn-danger{
  background: transparent;
  color: var(--sienna);
  border-color: var(--sienna);}
.btn-icon{
  width: 44px; min-height: 44px; padding: 0;
  background: var(--bg-card);
  border-color: var(--rule);
  color: var(--ink-2);}
.btn-sm{ min-height: 28px; padding: var(--space-1) var(--space-3); font-size: var(--fs-xs); }
/* iter070: hide ☰ (nav-toggle) and ⋯ (topbar-menu-toggle) on desktop. This rule
   MUST sit AFTER `.btn{ display: inline-flex }` above — both are single-class
   selectors (0, 1, 0), so when this was at the top of the topbar block `.btn` won
   on source order and the two toggles leaked as dead buttons on desktop. Placed
   here it wins on source order. The <=768px media query re-shows them (same
   0, 1, 0, later in the file) so mobile/landing behaviour is unchanged. */
.nav-toggle, .topbar-menu-toggle{ display: none; }

/* badges / status pills */
.badge{
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
  white-space: nowrap;}
.badge::before{ content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; opacity: .7; }
.badge.no-dot::before{ display: none; }
.badge.ready, .badge.succeeded, .badge.done, .badge.approve, .badge.success{ color: var(--jade-strong); background: var(--jade-soft); border-color: var(--jade-soft); }
.badge.warn, .badge.queued, .badge.warning, .badge.abstain, .badge.unknown{ color: var(--gold); background: var(--gold-soft); border-color: var(--gold-soft); }
.badge.blocked, .badge.failed, .badge.aborted, .badge.reject, .badge.lost, .badge.danger{ color: var(--sienna); background: var(--sienna-soft); border-color: var(--sienna-soft); }
.badge.running, .badge.pending{ color: var(--amber-strong); background: var(--amber-soft); border-color: var(--amber-soft); }
.badge-novel{ color: var(--jade-strong); background: var(--jade-soft); border-color: var(--jade-soft); }
.badge-muted{ color: var(--ink-3); background: var(--bg-sunken); border-color: var(--rule); }

/* card */
.card{
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  overflow: hidden;}
.card-header{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--rule);}
.card-header h3{ font-size: var(--fs-lg); }
.card-header .lead{ color: var(--ink-3); font-size: var(--fs-sm); margin: 2px 0 0; }
.card-body{ padding: var(--space-5); display: flex; flex-direction: column; gap: var(--space-4); }
.card-footer{
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--rule);
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  background: var(--bg-sunken);}
.card.flush .card-body{ padding: 0; }

/* grid utilities */
.grid{ display: grid; gap: var(--space-4); }
.grid.cols-2{ grid-template-columns: repeat(2, minmax(0, 1fr)); }
.grid.cols-3{ grid-template-columns: repeat(3, minmax(0, 1fr)); }
.grid.cols-auto{ grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
.style-preset-card.active{ border-color: var(--jade); background: var(--jade-soft); }
.style-preset-card h4{ margin: 0 0 4px; font-size: var(--fs-md); }
.style-preset-card .card-body{ padding: var(--space-3); }
.cluster{ display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; }
.stack{ display: flex; flex-direction: column; gap: var(--space-3); }

/* kv-list */
.kv-list{
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: var(--space-2) var(--space-4);
  font-size: var(--fs-sm);}
.kv-list .k{ color: var(--ink-3); }
.kv-list .v{ color: var(--ink-1); word-break: break-word; }
.kv-list .v code{ color: var(--ink-2); }
.kv-list.compact{ font-size: var(--fs-xs); gap: var(--space-1) var(--space-3); }

/* forms */
.field{ display: flex; flex-direction: column; gap: var(--space-1); font-size: var(--fs-sm); }
.field label{ color: var(--ink-2); font-weight: 500; font-size: var(--fs-xs); }
.field input, .field select, .field textarea{
  width: 100%;
  min-height: 36px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius-1);
  background: var(--bg-card);
  color: var(--ink-1);
  font-family: inherit;
  font-size: var(--fs-sm);}
.field input:focus, .field select:focus, .field textarea:focus{
  outline: 2px solid var(--jade);
  outline-offset: 0;
  border-color: var(--jade);}
.field-check{
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--ink-1);
  font-size: var(--fs-sm);}
.field-check input{ width: auto; min-height: 0; }
.form-grid{ display: grid; gap: var(--space-3) var(--space-4); grid-template-columns: repeat(3, minmax(0, 1fr)); }
.form-grid-2{ display: grid; gap: var(--space-3) var(--space-4); grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-actions{ display: flex; justify-content: flex-end; gap: var(--space-2); align-items: center; }

/* tabs */
.tabs{ display: flex; flex-direction: column; gap: var(--space-4); }
.tab-list{
  display: flex;
  gap: var(--space-1);
  border-bottom: 1px solid var(--rule);
  overflow-x: auto;}
.tab{
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
  white-space: nowrap;}
.tab:hover{ color: var(--ink-1); }
.tab.active{ color: var(--jade-strong); border-bottom-color: var(--jade); }
.tab-panel{ display: none; }
.tab-panel.active{ display: block; }

/* breadcrumbs reused in sub-pages (under topbar) */
.subnav{
  display: flex;
  gap: var(--space-1);
  align-items: center;
  font-size: var(--fs-sm);
  color: var(--ink-3);}

/* empty-state */
.empty-state{
  text-align: center;
  padding: var(--space-7) var(--space-5);
  background: var(--bg-card);
  border: 1px dashed var(--rule-strong);
  border-radius: var(--radius-2);
  color: var(--ink-2);}
.empty-state .ornament{ color: var(--jade); font-size: var(--fs-h2); display: block; margin-bottom: var(--space-3); }
.empty-state h3{ margin-bottom: var(--space-2); color: var(--ink-1); }
.empty-state .cta{ margin-top: var(--space-4); }
.empty-state .cta.cluster{ justify-content: center; }

/* skeleton — replaces "loading..." */
.skeleton{
  background: linear-gradient(90deg, var(--bg-sunken) 0%, #EFE7D6 50%, var(--bg-sunken) 100%);
  background-size: 200% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
  border-radius: var(--radius-1);
  color: transparent;
  min-height: 1em;}
.skeleton.row{ height: 14px; margin: 6px 0; }
.skeleton.row.short{ width: 40%; }
.skeleton.row.long{ width: 88%; }
.skeleton-block{ padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-2); }
@keyframes shimmer { 0%{ background-position: 200% 0; } 100%{ background-position: -200% 0; } }

/* toast placeholder */
.toast-stack{ position: fixed; bottom: var(--space-5); right: var(--space-5); display: flex; flex-direction: column; gap: var(--space-2); z-index: 50; }
.toast{
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
  box-shadow: 0 2px 6px rgba(42, 37, 32, .08);}
.toast.error{ border-left-color: var(--sienna); }
.toast.warn{ border-left-color: var(--gold); }
.toast-dismiss{
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font-size: var(--fs-sm);
  padding: 0;}

/* alerts inline */
.alert{
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-1);
  font-size: var(--fs-sm);
  border: 1px solid var(--rule);
  background: var(--bg-card);}
.alert.error{ background: var(--sienna-soft); border-color: var(--sienna-soft); color: var(--sienna); }
.alert.warn{ background: var(--gold-soft); border-color: var(--gold-soft); color: var(--amber-strong); }
.alert.info{ background: var(--jade-soft); border-color: var(--jade-soft); color: var(--jade-strong); }

/* tables */
.table{ width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.table th, .table td{ padding: var(--space-2) var(--space-3); text-align: left; vertical-align: top; border-bottom: 1px solid var(--rule); }
.table th{ font-weight: 600; color: var(--ink-2); font-size: var(--fs-xs); text-transform: none; letter-spacing: 0.04em; background: var(--bg-sunken); }
.table tbody tr{ transition: background .12s ease; }
.table tbody tr:hover{ background: var(--bg-sunken); }
.table .link-cell{ color: var(--jade); cursor: pointer; }
.table-scroll{
  width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;}
.table-wide{ min-width: 760px; }
.jobs-table{ min-width: 920px; }
.job-toggle{
  width: 28px;
  min-height: 28px;
  padding: 0;}
.job-drawer-row{ display: none; }
.job-drawer-row.open{ display: table-row; }
.job-drawer{
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--bg-card);
  border-left: 3px solid var(--jade);}
.job-drawer .drawer-grid{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-3);}
.job-drawer pre{
  max-height: 240px;
  overflow: auto;
  margin: 0;
  background: var(--bg-sunken);
  padding: var(--space-3);
  border-radius: var(--radius-1);}

/* progress */
.progress{ height: 8px; background: var(--bg-sunken); border-radius: var(--radius-pill); overflow: hidden; }
.progress-fill{ height: 100%; background: var(--amber); transition: width .3s ease; }

/* command list (recommended commands) */
.command-list{ display: flex; flex-direction: column; gap: var(--space-2); }
.command-list code{
  display: block;
  padding: var(--space-2) var(--space-3);
  background: var(--bg-sunken);
  border-radius: var(--radius-1);
  color: var(--ink-1);
  white-space: pre-wrap;}

/* ---------- page: dashboard / workspace shelf ---------- */
.shelf-stats{ display: flex; gap: var(--space-2); flex-wrap: wrap; }
.workspace-grid{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: var(--space-4); }
.workspace-card{
  display: block;
  padding: var(--space-5);
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  color: var(--ink-1);
  text-decoration: none;
  transition: border-color .15s ease, transform .12s ease;}
.workspace-card:hover{ border-color: var(--jade); transform: translateY(-1px); }
.workspace-card .card-head{ display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-3); margin-bottom: var(--space-4); }
.workspace-card h3{ font-size: var(--fs-h2); }
.workspace-card .metrics{ display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-3); }
.workspace-card .metric .k{ display: block; font-size: var(--fs-xs); color: var(--ink-3); }
.workspace-card .metric .v{ display: block; margin-top: 2px; font-size: var(--fs-lg); font-weight: 600; color: var(--ink-1); }
.workspace-card .metric .v.metric-small{ font-size: var(--fs-sm); }
.workspace-card .metric.history{ opacity: .6; }

.sidebar-job{
  margin-bottom: var(--space-2);}
.sidebar-job.history{ opacity: .6; }

/* ---------- page: workspace overview ---------- */
.overview-hero{
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: var(--space-5);
  align-items: stretch;}
.next-action{
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);}
.next-action .eyebrow{ margin-bottom: 0; }
.next-action .hint{ color: var(--ink-2); }
.next-action .cta-row{ display: flex; gap: var(--space-2); margin-top: var(--space-2); flex-wrap: wrap; }

.metric-pair{
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-3);}
.metric-pair .tile{
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  padding: var(--space-4);}
.metric-pair .tile .k{ font-size: var(--fs-xs); color: var(--ink-3); }
.metric-pair .tile .v{ font-size: var(--fs-display); font-weight: 600; color: var(--ink-1); font-family: var(--font-serif); }
.metric-pair .tile .v.metric-small{ font-size: var(--fs-xl); line-height: 1.25; }
.metric-pair .tile .sub{ font-size: var(--fs-xs); color: var(--ink-3); }

.details-fold summary{
  cursor: pointer;
  font-size: var(--fs-sm);
  color: var(--ink-2);
  padding: var(--space-2) 0;
  list-style: none;}
.details-fold summary::before{ content: "▸"; margin-right: .35em; color: var(--ink-3); }
.details-fold[open] summary::before{ content: "▾"; }

/* ---------- page: continue (cockpit) ---------- */
.readiness-primary{
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  background: var(--bg-card);}
.readiness-primary .copy{ display: flex; flex-direction: column; gap: var(--space-1); }
.readiness-primary h3{ font-size: var(--fs-lg); }
.readiness-primary p{ color: var(--ink-2); margin: 0; }
.readiness-status-row{ margin-top: var(--space-3); }
.readiness-diagnostics{ margin-top: var(--space-3); }
.continue-flow{
  display: flex;
  flex-direction: column;
  gap: var(--space-5);}
.flow-step{
  display: grid;
  grid-template-columns: 32px 1fr;
  gap: var(--space-4);}
.flow-step .step-mark{
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--jade-soft);
  color: var(--jade-strong);
  font-family: var(--font-serif);
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;}
.flow-step.done .step-mark{ background: var(--jade); color: #fff; }

/* ---------- page: chapters list ---------- */
.chapters-filter{
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
  align-items: center;}
.chapters-filter input[type=search]{
  min-height: 36px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius-1);
  min-width: 220px;
  background: var(--bg-card);
  font: inherit;}
.filter-toggle .btn{ border-radius: var(--radius-1); }
.filter-toggle .btn.active{ background: var(--jade-soft); border-color: var(--jade); color: var(--jade-strong); }

/* ---------- page: chapter detail ---------- */
.chapter-meta-bar{
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;}
.reading-body{
  max-width: var(--reading-w);
  margin: 0 auto;
  padding: var(--space-5) 0;
  font-family: var(--font-serif);
  font-size: var(--fs-lg);
  line-height: 1.95;
  color: var(--ink-1);}
.reading-body p{ margin: 0 0 1.1em; text-indent: 2em; }
.reading-body h1, .reading-body h2{ text-indent: 0; text-align: center; margin: 1.5em 0 .8em; }
.reading-body .jump-highlight{ background-color: var(--gold-soft); transition: background-color 1.5s ease; }
.review-card{
  display: grid;
  grid-template-columns: minmax(140px, 1fr) 2fr;
  gap: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  background: var(--bg-card);}
.review-card .name{ font-family: var(--font-serif); font-size: var(--fs-lg); }
.review-card .verdict{ margin-top: var(--space-1); }
.subscore-bar{ display: flex; align-items: center; gap: var(--space-2); font-size: var(--fs-xs); color: var(--ink-2); }
.subscore-bar .label{ width: 56px; }
.subscore-bar .track{ flex: 1; height: 6px; background: var(--bg-sunken); border-radius: var(--radius-pill); overflow: hidden; }
.subscore-bar .track > i{ display: block; height: 100%; background: var(--jade); }
.subscore-bar .val{ width: 32px; text-align: right; }
.subscore-cell{
  text-align: center;
  font-family: var(--font-mono);}
.subscore-cell-empty{
  color: var(--ink-3);
  background: var(--bg-card);}
.subscore-cell-approve{ background: var(--jade-soft); }
.subscore-cell-warn{ background: var(--gold-soft); }
.subscore-cell-fail{ background: var(--sienna-soft); }

.lint-group{ border: 1px solid var(--rule); border-radius: var(--radius-2); background: var(--bg-card); overflow: hidden; }
.lint-group h4{ padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--rule); background: var(--bg-sunken); font-size: var(--fs-sm); }
.lint-group ul{ list-style: none; padding: 0; margin: 0; }
.lint-group li{ padding: var(--space-2) var(--space-4); border-bottom: 1px solid var(--rule); font-size: var(--fs-sm); display: flex; gap: var(--space-3); }
.lint-group li:last-child{ border-bottom: 0; }
.lint-group li.link-cell{ cursor: pointer; }
.lint-group li.link-cell:hover{ background: var(--bg-sunken); }
.lint-group li .anchor{ color: var(--ink-3); font-family: var(--font-mono); font-size: var(--fs-xs); }
.lint-group li .severity{ color: var(--gold); font-size: var(--fs-xs); }
.lint-group li .severity.error{ color: var(--sienna); }
.lint-group li .severity.warn{ color: var(--gold); }

.advisor-item{
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  padding: var(--space-4);}
.advisor-item .type{ font-size: var(--fs-xs); color: var(--jade); text-transform: uppercase; letter-spacing: .04em; }
.advisor-item .section{ font-family: var(--font-serif); font-size: var(--fs-lg); margin-top: 2px; }
.advisor-item .guidance{ color: var(--ink-2); margin-top: var(--space-2); white-space: pre-wrap; }

/* iter 074: chapter version diff (history tab) — iter075 观感打磨（不改数据流/端点） */
.diff-panel{ margin-top: var(--space-5); padding-top: var(--space-4); border-top: 1px solid var(--rule); }
.diff-panel > h4{ font-size: var(--fs-sm); margin: 0 0 var(--space-3); color: var(--ink-2); letter-spacing: .02em; }
.diff-controls{ display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; font-size: var(--fs-sm); color: var(--ink-2); }
.diff-controls label{ display: inline-flex; align-items: center; gap: var(--space-2); }
.diff-controls select{
  max-width: 260px; padding: var(--space-1) var(--space-2);
  border: 1px solid var(--rule-strong); border-radius: var(--radius-1);
  background: var(--bg-card); color: var(--ink-1); font-size: var(--fs-sm);}
.diff-controls select:focus{ outline: none; border-color: var(--jade); box-shadow: 0 0 0 2px var(--jade-soft); }
.diff-controls .diff-arrow{ color: var(--ink-3); }
.diff-output{ margin-top: var(--space-3); }
.diff-view{
  border: 1px solid var(--rule); border-radius: var(--radius-2); overflow: auto;
  font-family: var(--font-mono); font-size: var(--fs-xs); line-height: 1.65;
  background: var(--bg-card); max-height: 480px; box-shadow: var(--shadow-card);}
.diff-line{ padding: 1px var(--space-3); white-space: pre-wrap; word-break: break-word; border-left: 3px solid transparent; }
.diff-line.diff-add{ background: var(--jade-soft); border-left-color: var(--jade); }
.diff-line.diff-del{ background: var(--sienna-soft); border-left-color: var(--sienna); }
.diff-line.diff-hunk{ color: var(--ink-3); background: var(--bg-sunken); }
.diff-line.diff-meta{ color: var(--ink-3); background: var(--bg-sunken); font-style: italic; }
.diff-line.diff-ctx{ color: var(--ink-2); }

/* iter075: 全文搜索页 */
.search-hero{ display: flex; flex-direction: column; gap: var(--space-3); margin-bottom: var(--space-4); }
.search-box-wrap{ position: relative; display: flex; align-items: center; }
.search-box-wrap .search-icon{ position: absolute; left: var(--space-4); color: var(--jade); font-size: var(--fs-lg); pointer-events: none; opacity: .7; }
.search-box{
  width: 100%;
  padding: var(--space-3) var(--space-4) var(--space-3) calc(var(--space-6) + var(--space-2));
  font-size: var(--fs-lg); font-family: var(--font-serif);
  border: 1px solid var(--rule-strong); border-radius: var(--radius-2);
  background: var(--bg-card); color: var(--ink-1);}
.search-box::placeholder{ color: var(--ink-3); }
.search-box:focus{ outline: none; border-color: var(--jade); box-shadow: 0 0 0 3px var(--jade-soft); }
.search-sources{ gap: var(--space-4); font-size: var(--fs-sm); color: var(--ink-2); }
.search-sources label{ display: inline-flex; align-items: center; gap: var(--space-1); cursor: pointer; }
.search-summary{ margin: 0 0 var(--space-4); font-size: var(--fs-sm); }
.search-results{ display: flex; flex-direction: column; gap: var(--space-4); }
.search-hit{ padding: var(--space-4); }
.search-hit-head{ display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-2); flex-wrap: wrap; }
.search-hit-title{ font-family: var(--font-serif); font-size: var(--fs-lg); color: var(--ink-1); text-decoration: none; }
.search-hit-count{ margin-left: auto; font-size: var(--fs-xs); color: var(--ink-3); }
.search-snippet{
  font-family: var(--font-serif); font-size: var(--fs-md); line-height: 1.9;
  color: var(--ink-2); margin: var(--space-2) 0 0; white-space: pre-wrap; word-break: break-word;}
.search-snippet + .search-snippet{ padding-top: var(--space-2); border-top: 1px dashed var(--rule); }
.search-snippet mark{
  background: var(--amber-soft); color: var(--amber-strong);
  padding: 0 2px; border-radius: var(--radius-1); font-weight: 600;}
/* source badge 三色：original=金(参照)、draft=品牌绿(可编辑)、kb=砖红(参考) */
.badge.source-original{ color: var(--gold); background: var(--gold-soft); border-color: var(--gold-soft); }
.badge.source-draft{ color: var(--jade-strong); background: var(--jade-soft); border-color: var(--jade-soft); }
.badge.source-kb{ color: var(--sienna); background: var(--sienna-soft); border-color: var(--sienna-soft); }

/* ---------- Review / advisor readability polish (global) ---------- */
.subscore-bar .track{ height: 8px; }
.subscore-bar .val{ font-family: var(--font-serif); font-size: var(--fs-sm); color: var(--ink-1); }
.badge.approve, .badge.reject{ font-weight: 700; }
.advisor-item{ border-left: 3px solid var(--jade); }

/* ---------- page: jobs ---------- */
.job-row .trace{
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--ink-3);}
.copy-btn{
  background: transparent;
  border: 1px solid var(--rule);
  border-radius: var(--radius-1);
  padding: 2px 6px;
  font-size: 11px;
  color: var(--ink-3);
  cursor: pointer;}
.copy-btn:hover{ color: var(--ink-1); background: var(--bg-sunken); }
.logs-tail{
  background: var(--bg-sunken);
  border: 1px solid var(--rule);
  border-radius: var(--radius-1);
  padding: var(--space-3);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  max-height: 360px;
  overflow: auto;
  color: var(--ink-1);}

/* ---------- wizard + settings (slim pages) ---------- */
.slim-shell{
  max-width: 720px;
  margin: 0 auto;
  padding: var(--space-7) var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-5);}
.wizard-mode-card{ margin: 0; }
.wizard-help-card{
  padding: var(--space-4);
  background: var(--bg-sunken);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);}
.wizard-help-card .eyebrow{ margin-bottom: var(--space-2); }
.wizard-advanced{ border-top: 1px solid var(--rule); padding-top: var(--space-2); }
.wizard-progress-actions{
  margin-top: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);}
.wizard-progress-actions .cluster{ justify-content: flex-start; }

/* confirm modal */
.modal-backdrop{
  position: fixed; inset: 0;
  background: var(--bg-overlay);
  display: flex; align-items: center; justify-content: center;
  z-index: 40;
  padding: var(--space-5);}
.modal{
  width: 100%;
  max-width: 480px;
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  box-shadow: var(--shadow-card);
  overflow: hidden;}
.modal-header{
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--rule);
  font-family: var(--font-serif);
  font-size: var(--fs-lg);}
.modal-body{ padding: var(--space-5); display: flex; flex-direction: column; gap: var(--space-3); }
.modal-footer{
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--rule);
  background: var(--bg-sunken);
  display: flex; justify-content: flex-end; gap: var(--space-2);}
/* iter071 (codex F6): the 3-way leave-guard footer — equal-width, single-line
   buttons so the choices read as a tidy, consistent row instead of ragged
   content-sized boxes that wrap at different points. */
.modal-footer-equal .btn{ flex: 1 1 0; min-width: 0; white-space: nowrap; }

/* ---------- responsive ---------- */
@media (max-width: 1024px){
  .overview-hero { grid-template-columns: 1fr; }
  .grid.cols-3, .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }}

/* ---------- Landing page (investor entry) ---------- */
.lp{
  max-width: 960px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  padding: var(--space-5) 0 var(--space-7);}
.lp-hero{
  text-align: center;
  padding: var(--space-8) var(--space-7);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  background:
    radial-gradient(120% 80% at 18% 0%, var(--jade-soft) 0%, transparent 55%),
    radial-gradient(100% 80% at 92% 8%, var(--amber-soft) 0%, transparent 50%),
    var(--bg-card);}
.lp-hero-brand{
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-4);}
.lp-wordmark{
  font-family: var(--font-serif);
  font-size: var(--fs-h2);
  font-weight: 600;
  color: var(--ink-1);
  letter-spacing: .02em;}
.lp-hero .eyebrow{ justify-content: center; }
.lp-title{
  font-family: var(--font-serif);
  font-size: var(--fs-display);
  line-height: 1.25;
  margin: var(--space-3) 0 var(--space-4);
  color: var(--ink-1);}
.lp-lead{
  max-width: 36em;
  margin: 0 auto var(--space-5);
  font-size: var(--fs-lg);
  line-height: 1.7;}
.lp-hero-cta{ justify-content: center; }
.lp-hero-cta .btn{ min-width: 132px; }

.lp-cards{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-5);}
/* iter069: 3 cards degrade to 2 columns on tablets, then to 1 column at
   <=768px (in the mobile block below). This rule MUST sit after the base
   3-col rule above — equal specificity, so source order decides the winner;
   placing it inside the earlier responsive @media block let the later base
   rule override it and stranded a cramped 3-up row at ~800px. */
@media (max-width: 1024px){
  .lp-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }}
.lp-card{
  display: flex;
  flex-direction: column;
  transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease;}
.lp-card:hover{
  transform: translateY(-2px);
  border-color: var(--rule-strong);
  box-shadow: 0 6px 20px rgba(42, 37, 32, .08);}
.lp-card .card-body{
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);}
.lp-card-head{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);}
.lp-card-head h2{
  font-family: var(--font-serif);
  font-size: var(--fs-h2);
  margin: 0;
  color: var(--ink-1);}
.lp-feats{
  list-style: none;
  margin: var(--space-2) 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);}
.lp-feats li{
  position: relative;
  padding-left: var(--space-5);
  font-size: var(--fs-sm);
  color: var(--ink-2);
  line-height: 1.5;}
.lp-feats li::before{
  content: "✦";
  position: absolute;
  left: 0;
  top: 0;
  color: var(--jade);
  font-size: var(--fs-xs);}
.lp-feat-beta{ color: var(--ink-3); }
.lp-feat-beta::before{ color: var(--gold); }
.lp-card-footer .btn{ width: 100%; justify-content: center; }

.lp-trust{
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding-top: var(--space-3);}
.lp-metrics{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);}
.lp-metrics .tile{
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-4);
  background: var(--bg-card);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);}
.lp-metrics .tile .v{
  font-family: var(--font-serif);
  font-size: var(--fs-display);
  line-height: 1;
  color: var(--jade-strong);}
.lp-metrics .tile .k{
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--ink-1);}
.lp-metrics .tile .sub{
  font-size: var(--fs-xs);
  color: var(--ink-3);}
.lp-chips{ justify-content: center; flex-wrap: wrap; }

@keyframes lp-fade-up {
  from{ opacity: 0; transform: translateY(12px); }
  to{ opacity: 1; transform: translateY(0); }
}
.fade-up{ animation: lp-fade-up .5s ease both; }
.fade-up-1{ animation-delay: .08s; }
.fade-up-2{ animation-delay: .16s; }
.fade-up-3{ animation-delay: .24s; }
.fade-up-4{ animation-delay: .32s; }
@media (prefers-reduced-motion: reduce) {
  .fade-up, .fade-up-1, .fade-up-2, .fade-up-3, .fade-up-4{ animation: none; }
}

@media (max-width: 768px) {
  .app{ grid-template-columns: 1fr; }
  .sidebar{
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
  .sidebar.open{ transform: translateX(0); }
  .sidebar-overlay.open{
    display: block;
    position: fixed;
    inset: 0;
    background: var(--bg-overlay);
    z-index: 30;
  }
  .app.no-context .nav-toggle{ display: none; }
  .nav-toggle{ display: inline-flex; flex: 0 0 36px; }
  .topbar{
    padding: var(--space-3) var(--space-4);
    gap: var(--space-2);
  }
  .topbar .breadcrumb{
    min-width: 0;
    flex: 1;
    overflow: hidden;
    white-space: nowrap;
  }
  .breadcrumb a, .breadcrumb .here{
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 42vw;
  }
  .topbar-menu-toggle{ display: inline-flex; }
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
  .table-scroll{
    margin: 0 calc(-1 * var(--space-4));
    padding: 0 var(--space-4) var(--space-2);
    background:
      linear-gradient(to right, var(--bg-card) 30%, rgba(255, 254, 251, 0)) left center / 36px 100% no-repeat local,
      linear-gradient(to left, var(--bg-card) 30%, rgba(255, 254, 251, 0)) right center / 36px 100% no-repeat local,
      radial-gradient(farthest-side at 0 50%, rgba(42, 37, 32, .18), rgba(42, 37, 32, 0)) left center / 12px 100% no-repeat scroll,
      radial-gradient(farthest-side at 100% 50%, rgba(42, 37, 32, .18), rgba(42, 37, 32, 0)) right center / 12px 100% no-repeat scroll;
  }
  .page{ padding: var(--space-4); }
  .page-header{
    align-items: flex-start;
    flex-direction: column;
  }
  .page-header h1{ font-size: var(--fs-h1); }
  .form-grid, .grid.cols-2, .form-grid-2{ grid-template-columns: 1fr; }
  .review-card{ grid-template-columns: 1fr; }
  .lp{ padding: var(--space-4) 0 var(--space-6); gap: var(--space-5); }
  .lp-hero{ padding: var(--space-6) var(--space-5); }
  .lp-title{ font-size: var(--fs-h1); }
  .lp-cards{ grid-template-columns: 1fr; }
  .lp-metrics{ grid-template-columns: 1fr; }
}

/* ====================================================================== *
 * iter062: friendly error cards + workbench step rail + locked tabs +
 * topbar home button. All built on existing tokens (paper/ink/jade/amber/
 * sienna), no new colours.
 * ====================================================================== */

/* topbar home: cluster nav-toggle + home + breadcrumb on the left, push
 * the page actions to the far right (override the bare space-between). */
.topbar .home-btn{ flex: 0 0 auto; }
.topbar .breadcrumb{ margin-right: auto; }
/* iter069: landing (page_kind=="landing" → .app.lp-chrome) hides the shared
   topbar nav cluster so the hero keeps only ⚙ 设置. We hide ONLY ☰ (nav-toggle)
   and ⌂ (home-btn): ⌂ is the sole element shown at every breakpoint, and ☰ is
   redundant on a sidebar-less landing. We deliberately do NOT hide ⋯
   (.topbar-menu-toggle): on desktop it's already hidden by the base
   `.nav-toggle, .topbar-menu-toggle{display:none}` rule (relocated in iter070 to
   sit after `.btn` so source order wins), and ⚙ 设置 shows inline, but on
   <=768px ⋯ is the ONLY way to open the
   .topbar-actions dropdown that holds ⚙ 设置 — hiding it would strand the lone
   landing action on mobile. .lp-chrome X (0-2-0) beats the desktop default and
   the <=768px home-btn rules (all 0-1-0); display:none also drops these from
   the a11y tree (no aria-hidden needed). Scoped to landing via APP_CLASS so
   wizard/settings keep their ⌂ / ⋯. */
.lp-chrome .nav-toggle, .lp-chrome .home-btn{ display: none; }
html{ scroll-behavior: smooth; }

/* friendly error card (replaces bare .alert.error traceback dumps) */
.error-card{
  background: var(--sienna-soft);
  border: 1px solid var(--sienna);
  border-radius: var(--radius-2);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);}
.error-card-head{ display: flex; gap: var(--space-3); align-items: flex-start; }
.error-card-icon{ color: var(--sienna); font-size: var(--fs-xl); line-height: 1.2; flex: 0 0 auto; }
.error-card-copy{ min-width: 0; }
.error-card-title{ font-weight: 600; color: var(--ink-1); margin: 0; }
.error-card-cause{ color: var(--ink-2); margin: 4px 0 0; font-size: var(--fs-sm); }
.error-card-actions{ margin: 0; }
.error-card-trace{ margin: 0; font-size: var(--fs-xs); color: var(--ink-3); }
.error-card-trace code{ color: var(--ink-2); }
.error-card-tech{ margin: 0; }
.error-card-tech > summary{ cursor: pointer; font-size: var(--fs-xs); color: var(--ink-3); }
.error-card-tech pre{
  background: var(--bg-sunken); border-radius: var(--radius-1);
  padding: var(--space-2) var(--space-3); font-size: var(--fs-xs);
  color: var(--ink-2); margin: var(--space-2) 0 0;}

/* workbench clickable step rail */
.stepbar{ list-style: none; display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); margin: 0; padding: 0; }
.stepbar .step{ display: flex; align-items: center; font-size: var(--fs-sm); color: var(--ink-3); }
.stepbar .step a{ color: var(--ink-2); border: 0; display: inline-flex; align-items: center; gap: var(--space-2); }
.stepbar .step a:hover{ color: var(--jade); border: 0; }
.stepbar .step.done, .stepbar .step.done a{ color: var(--jade-strong); }
.stepbar .step.current, .stepbar .step.current a{ color: var(--amber-strong); font-weight: 600; }
.stepbar .step.locked{ color: var(--ink-3); cursor: not-allowed; }
.stepbar .step:not(:last-child)::after{ content: "›"; color: var(--ink-3); margin-left: var(--space-3); }
.stepbar .step-glyph{
  display: inline-flex; width: 18px; height: 18px; border-radius: 50%;
  align-items: center; justify-content: center; font-size: var(--fs-xs);
  background: var(--bg-sunken); color: var(--ink-3);}
.stepbar .step.done .step-glyph{ background: var(--jade); color: #fff; }
.stepbar .step.current .step-glyph{ background: var(--amber-soft); color: var(--amber-strong); box-shadow: inset 0 0 0 2px var(--amber); }

@media (max-width: 720px) {
  .form-actions{ flex-wrap: wrap; justify-content: stretch; }
  .form-actions .btn{ flex: 1 1 140px; }
  button, .btn{ min-height: 44px; }
  .btn-sm{ min-height: 44px; }
}

:where(.ui-public, .ui-novel) {
  background: var(--ui-page-bg);
  color: var(--ui-text);}
:where(.ui-public, .ui-novel) .card, :where(.ui-public, .ui-novel) .sidebar, :where(.ui-public, .ui-novel) .modal, :where(.ui-public, .ui-novel) .toast {
  background: var(--ui-card-bg);}
:where(.ui-public, .ui-novel) .btn {
  min-height: 44px;
  min-width: 44px;
  color: var(--ui-text);
  border-radius: var(--radius-2);}
:where(.ui-public, .ui-novel) button {
  min-height: 44px;
  min-width: 44px;}
:where(.ui-public, .ui-novel) .btn-primary {
  background: var(--ui-primary-bg);
  color: var(--ui-brand-text);
  border-color: #B8CEC1;}
:where(.ui-public, .ui-novel) .btn-primary:hover:not(:disabled){
  background: #D8E8DE;
  color: var(--ui-brand-text);
  border-color: var(--ui-focus-ring);}
:where(.ui-public, .ui-novel) .btn-secondary{
  background: var(--ui-card-bg);
  color: var(--ui-text);
  border-color: var(--rule-strong);}
:where(.ui-public, .ui-novel) .btn-secondary:hover:not(:disabled){
  background: var(--ui-primary-bg);
  border-color: #B8CEC1;}
:where(.ui-public, .ui-novel) .btn-ghost{
  background: transparent;
  color: var(--ui-text-muted);
  border-color: transparent;}
:where(.ui-public, .ui-novel) .btn-paid {
  background: var(--ui-paid-bg);
  color: var(--ui-text);
  border-color: #D8AE7E;}
:where(.ui-public, .ui-novel) .btn-paid:hover:not(:disabled){
  background: #F3DBC0;
  color: var(--ui-text);
  border-color: #B97B43;}
:where(.ui-public, .ui-novel) .btn-danger {
  background: var(--ui-danger-bg);
  color: var(--ui-danger-text);
  border-color: #D8A18F;}
:where(.ui-public, .ui-novel) .btn-danger:hover:not(:disabled){
  background: #EFCFC2;
  color: #7F3D2E;
  border-color: var(--ui-danger-text);}
:where(.ui-public, .ui-novel) .btn:focus-visible, :where(.ui-public, .ui-novel) .tab:focus-visible, :where(.ui-public, .ui-novel) .sidebar-item:focus-visible, :where(.ui-public, .ui-novel) a:focus-visible, :where(.ui-public, .ui-novel) input:focus-visible, :where(.ui-public, .ui-novel) select:focus-visible, :where(.ui-public, .ui-novel) textarea:focus-visible{
  outline: 3px solid var(--ui-focus-ring);
  outline-offset: 2px;}
:where(.ui-public, .ui-novel) .btn:active:not(:disabled){
  transform: translateY(1px);}
:where(.ui-public, .ui-novel) .btn[disabled], :where(.ui-public, .ui-novel) .btn[aria-disabled="true"]{
  opacity: .52;
  cursor: not-allowed;
  transform: none;}
:where(.ui-public, .ui-novel) .btn[aria-busy="true"]::before{
  content: "";
  width: 14px;
  height: 14px;
  flex: 0 0 14px;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: ui-busy-spin .75s linear infinite;}
@keyframes ui-busy-spin { to{ transform: rotate(360deg); } }
:where(.ui-public, .ui-novel) .btn-icon {
  width: 44px;
  height: 44px;
  min-width: 44px;
  min-height: 44px;
  padding: 0;}
:where(.ui-public, .ui-novel) .field input, :where(.ui-public, .ui-novel) .field select, :where(.ui-public, .ui-novel) .field textarea{
  min-height: 44px;}
:where(.ui-public, .ui-novel) .field [aria-invalid="true"]{
  border-color: var(--ui-danger-text);
  box-shadow: 0 0 0 2px var(--ui-danger-bg);}
:where(.ui-public, .ui-novel) .field :disabled{
  background: var(--bg-sunken);
  color: var(--ui-text-muted);}
:where(.ui-public, .ui-novel) .field [readonly]{
  background: #F8F3EA;
  border-style: dashed;}
:where(.ui-public, .ui-novel) .required-note{
  color: var(--ui-danger-text);
  margin-left: var(--space-1);
  font-weight: 500;}
:where(.ui-public, .ui-novel) .field-error{
  color: var(--ui-danger-text);
  min-height: 1.4em;}
:where(.ui-public, .ui-novel) .sidebar-item, :where(.ui-public, .ui-novel) .tab{
  min-height: 44px;}
:where(.ui-public, .ui-novel) .sidebar-item.active{
  box-shadow: inset 4px 0 0 var(--ui-focus-ring);
  cursor: default;}
:where(.ui-public, .ui-novel) .stage-card, :where(.ui-public, .ui-novel) .workbench-stage-card{
  background: var(--ui-card-bg);
  border-color: var(--rule);}
@media (prefers-reduced-motion: reduce) {
  :where(.ui-public, .ui-novel) .btn[aria-busy="true"]::before{ animation: none; }
}
@media (max-width: 600px) {
  :where(.ui-public, .ui-novel) .workbench-stage-card > .card-header{
    align-items: flex-start;
    flex-direction: column;
  }
  :where(.ui-public, .ui-novel) .workbench-stage-card > .card-header h3{
    white-space: nowrap;
  }
}

/* iter154 Phase C: shared public-page structure. */
.ui-public .sr-status{
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;}
.ui-public .public-toolbar{
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: var(--space-5);
  padding: var(--space-4);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  background: var(--ui-card-bg);}
.ui-public .public-search{ flex: 1 1 360px; max-width: 520px; }
.ui-public .public-toolbar-actions{ justify-content: flex-end; }
.ui-public .workspace-list, .ui-public .trash-list{
  display: flex;
  flex-direction: column;
  gap: var(--space-4);}
.ui-public .public-work-card, .ui-public .trash-card{
  display: grid;
  grid-template-columns: minmax(190px, 1.15fr) minmax(320px, 2fr) auto;
  gap: var(--space-5);
  align-items: center;
  padding: var(--space-5);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  background: var(--ui-card-bg);}
.ui-public .public-work-card h2, .ui-public .trash-card h2{ font-size: var(--fs-h2); overflow-wrap: anywhere; }
.ui-public .public-work-meta, .ui-public .trash-meta{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3) var(--space-5);
  margin: 0;}
.ui-public .public-work-meta div, .ui-public .trash-meta div{ min-width: 0; }
.ui-public .public-work-meta dt, .ui-public .trash-meta dt{ color: var(--ui-text-muted); font-size: var(--fs-xs); }
.ui-public .public-work-meta dd, .ui-public .trash-meta dd{ margin: 2px 0 0; font-weight: 600; overflow-wrap: anywhere; }
.ui-public .public-work-actions, .ui-public .trash-actions{ justify-content: flex-end; }
.ui-public .public-notice, .ui-public .public-mode-summary, .ui-public .public-next-step{
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  background: var(--ui-primary-bg);}
.ui-public .public-next-step{ background: var(--ui-card-bg); }
.ui-public .public-next-step ol{
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-3);
  margin: 0;
  padding-left: var(--space-5);}
.ui-public .wizard-choice{
  min-height: 72px;
  align-items: flex-start;
  padding: var(--space-3);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  background: var(--ui-card-bg);}
.ui-public .field-check{
  min-height: 44px;
  cursor: pointer;}
.ui-public .breadcrumb a, .ui-public .wizard-mode-help a{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  min-height: 44px;
  padding-inline: var(--space-1);}
.ui-public .wizard-mode-help{ margin: calc(-1 * var(--space-1)) 0 var(--space-1); }
.ui-public .wizard-choice input{ margin-top: 4px; }
.ui-public .wizard-choice span{ display: flex; flex-direction: column; gap: var(--space-1); }
.ui-public .wizard-choice small{ color: var(--ui-text-muted); font-weight: 400; }
.ui-public form[aria-busy="true"]{ opacity: .78; }

@media (max-width: 1199px) {
  .ui-public .public-work-card, .ui-public .trash-card{ grid-template-columns: minmax(180px, 1fr) minmax(260px, 1.5fr); }
  .ui-public .public-work-actions, .ui-public .trash-actions{ grid-column: 1 / -1; justify-content: flex-start; }
  .ui-public .public-next-step ol{ grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 767px) {
  .ui-public .public-toolbar, .ui-public .public-work-card, .ui-public .trash-card{ display: flex; flex-direction: column; align-items: stretch; }
  .ui-public .public-search{ max-width: none; width: 100%; flex-basis: auto; }
  .ui-public .public-toolbar-actions, .ui-public .public-work-actions, .ui-public .trash-actions{ justify-content: stretch; width: 100%; }
  .ui-public .public-toolbar-actions .btn, .ui-public .public-work-actions .btn, .ui-public .trash-actions .btn{ flex: 1 1 100%; width: 100%; }
  .ui-public .public-work-meta, .ui-public .trash-meta{ grid-template-columns: 1fr; }
  .ui-public .public-next-step ol{ grid-template-columns: 1fr; }
  .ui-public .slim-shell{ padding: var(--space-4) 0 var(--space-6); }
  .ui-public .lp-hero{ padding: var(--space-5); }
  .ui-public .modal{ max-height: calc(100vh - 24px); overflow-y: auto; }
  .ui-public .toast-stack{ bottom: calc(var(--space-4) + env(safe-area-inset-bottom)); }
}
.ui-novel .workbench-running-note{
  margin: 0 0 var(--space-4);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius-2);
  background: var(--jade-soft);
  color: var(--ui-text);}
.ui-novel .phase-d-toolbar{
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(280px, auto) minmax(150px, 200px) auto;
  gap: var(--space-3);
  align-items: end;
  margin-bottom: var(--space-4);}
.ui-novel .field-label{ display: block; margin-bottom: var(--space-2); font-weight: 650; }
.ui-novel .chapter-items, .ui-novel .job-record-list{ display: grid; gap: var(--space-3); }
.ui-novel .chapter-item, .ui-novel .job-record-card{
  display: grid;
  grid-template-columns: minmax(240px, 1.4fr) minmax(300px, 1fr) auto;
  gap: var(--space-4);
  align-items: center;
  min-width: 0;
  padding: var(--space-4);
  border: 1px solid var(--rule);
  border-radius: var(--radius-2);
  background: var(--ui-card-bg);}
.ui-novel .chapter-item h2, .ui-novel .job-record-card h2{ margin: var(--space-2) 0 var(--space-1); overflow-wrap: anywhere; }
.ui-novel .chapter-item-meta{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
  margin: 0;}
.ui-novel .chapter-item-meta dt{ color: var(--ui-text-muted); font-size: var(--fs-xs); }
.ui-novel .chapter-item-meta dd{ margin: var(--space-1) 0 0; overflow-wrap: anywhere; }
.ui-novel .chapter-item-action, .ui-novel .job-record-action{ display: flex; justify-content: flex-end; }
.ui-novel .chapter-item-action .btn, .ui-novel .job-record-action .btn{ min-width: 132px; }
.ui-novel .save-state{
  min-height: 44px;
  display: flex;
  align-items: center;
  margin-top: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-1);
  background: var(--bg-sunken);}
.ui-novel .save-state.success{ background: var(--jade-soft); }
.ui-novel .save-state.warn{ background: var(--gold-soft); }
.ui-novel .save-state.error{ background: var(--ui-danger-bg); }
.ui-novel .save-state.busy{ background: var(--jade-soft); }
.ui-novel .jobs-filter{ margin-bottom: var(--space-4); }
.ui-novel .job-record-state p{ margin: var(--space-2) 0 0; color: var(--ui-text-muted); }
.ui-novel textarea, .ui-novel .reading-body, .ui-novel .chapter-item, .ui-novel .job-record-card{ max-width: 100%; overflow-wrap: anywhere; }
.ui-novel .brand, .ui-novel .breadcrumb a, .ui-novel .stepbar a, .ui-novel summary, .ui-novel input, .ui-novel select{
  box-sizing: border-box;
  min-height: 44px !important;}
.ui-novel .brand, .ui-novel .breadcrumb a, .ui-novel .stepbar a, .ui-novel summary{
  display: inline-flex;
  align-items: center;}
.ui-novel .breadcrumb a{ min-width: 44px; padding-inline: var(--space-2); justify-content: center; }
.ui-novel .stepbar a{ width: 100%; justify-content: center; }
.ui-novel summary{ width: 100%; padding-block: var(--space-2); }
.ui-novel input, .ui-novel select{ padding-block: 10px; }

@media (max-width: 1199px) {
  .ui-novel .phase-d-toolbar{ grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ui-novel .chapter-item, .ui-novel .job-record-card{ grid-template-columns: minmax(220px, 1fr) minmax(280px, 1.2fr); }
  .ui-novel .chapter-item-action, .ui-novel .job-record-action{ grid-column: 1 / -1; justify-content: flex-start; }
}
@media (max-width: 767px) {
  .ui-novel .phase-d-toolbar, .ui-novel .chapter-item, .ui-novel .job-record-card{ display: flex; flex-direction: column; align-items: stretch; }
  .ui-novel .phase-d-toolbar .btn, .ui-novel .chapter-item-action .btn, .ui-novel .job-record-action .btn{ width: 100%; }
  .ui-novel .chapter-item-meta{ grid-template-columns: 1fr; }
  .ui-novel .tab-list{ overflow-x: auto; max-width: 100%; padding-bottom: var(--space-1); }
  .ui-novel .tab{ flex: 0 0 auto; }
  .ui-novel .jobs-filter .btn{ flex: 1 1 calc(50% - var(--space-2)); }
  .ui-novel .reading-body{ padding-inline: var(--space-3); }
}

/* Iteration 156 · Phase E advanced and auxiliary pages. */
.ui-novel .advanced-entry-note{ margin-bottom: var(--space-4); }
.ui-novel .plan-page-editor{ max-width: 860px; margin-inline: auto; }
.ui-novel .plan-page-editor textarea{ width: 100%; resize: vertical; }
.ui-novel .search-hero{ display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: end; }
.ui-novel .search-box-wrap{ flex: 1 1 360px; min-width: 0; }
.ui-novel .search-sources{ flex: 1 1 360px; }
.ui-novel .search-sources label{ min-height: 44px; display: inline-flex; align-items: center; gap: var(--space-2); }
.ui-novel .search-hit{ position: relative; min-width: 0; padding-bottom: calc(var(--space-4) + 44px); overflow-wrap: anywhere; }
.ui-novel .search-hit-title, .ui-novel .search-snippet{ min-width: 0; overflow-wrap: anywhere; word-break: break-word; }
.ui-novel .search-hit-open{ position: absolute; right: var(--space-4); bottom: var(--space-4); }
.ui-novel .review-issue-list{ display: grid; gap: var(--space-4); }
.ui-novel .review-issue-card{ min-width: 0; overflow-wrap: anywhere; }
.ui-novel .review-safe-meta{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); margin: 0; }
.ui-novel .review-safe-meta dt{ color: var(--ui-text-muted); font-size: var(--fs-xs); }
.ui-novel .review-safe-meta dd{ margin: var(--space-1) 0 0; }
.ui-novel .insight-value{ overflow-wrap: anywhere; }
.ui-novel .insight-score-list{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
.ui-novel .insight-score-card{ min-width: 0; padding: var(--space-4); border: 1px solid var(--rule); border-radius: var(--radius-2); background: var(--ui-card-bg); }
.ui-novel .insight-score-card dl{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); margin: var(--space-3) 0 0; }
.ui-novel .insight-score-card dt{ color: var(--ui-text-muted); font-size: var(--fs-xs); }
.ui-novel .insight-score-card dd{ margin: var(--space-1) 0 0; overflow-wrap: anywhere; }
.ui-novel .review-issue-card .card-footer{ display: flex; justify-content: flex-end; }

@media (max-width: 767px) {
  .ui-novel .continue-flow .flow-step{ grid-template-columns: 36px minmax(0, 1fr); }
  .ui-novel .search-hero, .ui-novel .search-sources{ flex-direction: column; align-items: stretch; }
  .ui-novel .search-box-wrap, .ui-novel .search-sources{ flex-basis: auto; width: 100%; }
  .ui-novel .search-sources label, .ui-novel #search-clear, .ui-novel .search-hit-open, .ui-novel .review-issue-card .btn, .ui-novel .plan-page-editor .form-actions .btn{ width: 100%; }
  .ui-novel .search-hit-open{ position: static; margin-top: var(--space-3); }
  .ui-novel .search-hit{ padding-bottom: var(--space-4); }
  .ui-novel .review-safe-meta{ grid-template-columns: 1fr; }
  .ui-novel .insight-score-list, .ui-novel .insight-score-card dl{ grid-template-columns: 1fr; }
  .ui-novel .review-issue-card .card-header{ align-items: flex-start; }
  .ui-novel .review-issue-card .card-footer{ justify-content: stretch; }
  .ui-novel #insights-cost > div{ grid-template-columns: minmax(72px, auto) minmax(80px, 1fr) minmax(100px, auto) !important; }
}
button, input, select, textarea, [tabindex]):focus-visible{
  outline: 3px solid var(--ui-focus-ring);
  outline-offset: 3px;}
button, input, select, textarea, .sidebar-item{
  box-sizing: border-box;
  min-height: 44px;
  min-width: 44px;}

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
    const hints = {
      start_point_missing: "先选择从原作哪一章之后开始续写。",
      kb_missing: "先在工作台生成作品知识与角色设定。",
      extraction_coverage_missing: "起点附近的设定提取待补充，请重建续写底座。",
      outline_missing: "先生成或检查全书走向，再进入章节续写。",
      outline_stale: "大纲与当前起点不一致，请重新生成；已写正文不受影响。",
      outline_drift_severe: "近期剧情与大纲差异明显，建议重新生成大纲后再续写。",
      chapter_plan_missing: "续写前需要先生成本章计划。",
      chapter_plan_invalid: "章节计划无法读取，重新生成即可；已写正文不受影响。",
      retry_exhausted: "已有草稿未达通过门槛，可查看后重新开始。",
      preflight_failed: "当前运行条件尚未通过检查，请先查看待办。",
      foreshadowing_overdue: "有必须回收的伏笔尚未处理。",
      unknown: "续写条件尚未满足，请查看检查详情。",
    };
    for (const kind in cat) {
      if (!Object.prototype.hasOwnProperty.call(cat, kind)) continue;
      const spec = cat[kind] || {};
      out[kind] = {
        label: spec.label,
        action: spec.cta_action,
        cta_label: spec.cta_label,
        hint: hints[kind] || "请检查当前作品状态后再继续。",
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
    production: { tier: "mid", chapters: 1, max_retries: 2, budget_cny: 6, auto_advance: true },
    strict: { tier: "high", chapters: 1, max_retries: 3, budget_cny: 6, auto_advance: true },
  };
  const NOVEL_STAGE_LIMITS = Object.freeze({
    "expand-premise": { budget_cny: 1, timeout_minutes: 15, max_model_requests: 2 },
    "prepare-greenfield": { budget_cny: 3, timeout_minutes: 15, max_model_requests: 10 },
    "rebuild-for-start": { budget_cny: 3, timeout_minutes: 15, max_model_requests: 32 },
    debate: { budget_cny: 8, timeout_minutes: 60, max_model_requests: 45 },
    "plan-chapters": { budget_cny: 2, timeout_minutes: 15, max_model_requests: 3 },
    "write-book": { budget_cny: 6, timeout_minutes: 45, max_model_requests: 20 },
  });

  // ---- shared helpers ----------------------------------------------------
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }
  function setControlBusy(control, busy, label) {
    if (!control) return;
    if (busy) {
      if (control.getAttribute("aria-busy") !== "true") {
        control.dataset.uiIdleLabel = control.textContent.trim();
        control.dataset.uiWasDisabled = control.disabled ? "1" : "0";
      }
      control.disabled = true;
      control.setAttribute("aria-busy", "true");
      if (label) control.textContent = label;
    } else {
      control.disabled = control.dataset.uiWasDisabled === "1";
      control.removeAttribute("aria-busy");
      if (control.dataset.uiIdleLabel) control.textContent = control.dataset.uiIdleLabel;
      delete control.dataset.uiIdleLabel;
      delete control.dataset.uiWasDisabled;
    }
  }
  function setFormSubmitBusy(form, busy, label) {
    if (!form) return;
    if (busy) form.setAttribute("aria-busy", "true");
    else form.removeAttribute("aria-busy");
    const controls = Array.prototype.slice.call(form.querySelectorAll('button[type="submit"], input[type="submit"]'));
    if (form.id) {
      document.querySelectorAll('[form="' + CSS.escape(form.id) + '"]').forEach(function (control) {
        if (controls.indexOf(control) < 0) controls.push(control);
      });
    }
    controls.forEach(function (control) { setControlBusy(control, busy, label); });
  }
  // iter 050 (D1): keep status + payload on the thrown error and translate
  // the bare "workspace busy" 409 into an actionable message. Every caller
  // that renders err.message gets the friendly text for free.
  function _httpError(res, data) {
    let msg = data.error || ("HTTP " + res.status);
    if (res.status === 409 && data.running_job_id) {
      msg = "当前作品已有任务正在处理。请等待完成，或前往任务记录查看并请求取消。";
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
      headers: {
        "Content-Type": "application/json",
        "X-Workspace-Mutation-Intent": "mutate-v1",
      },
      body: JSON.stringify(payload || {}),
    }, opts || {}));
  }
  async function putJson(url, payload, opts) {
    return _fetchWrapped(url, Object.assign({
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-Workspace-Mutation-Intent": "mutate-v1",
      },
      body: JSON.stringify(payload || {}),
    }, opts || {}));
  }
  async function postModelRun(url, payload) {
    return _fetchWrapped(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Model-Action-Intent": "run-v1",
      },
      body: JSON.stringify(payload || {}),
    });
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
    const navToggles = Array.from(document.querySelectorAll("[data-sidebar-toggle]"));
    const topbarToggle = document.querySelector("[data-topbar-menu-toggle]");
    const topbarActions = document.querySelector(".topbar-actions");
    const main = document.querySelector(".main");
    const page = document.querySelector(".page");
    const topbar = topbarActions && topbarActions.closest(".topbar");
    const topbarWrap = topbarActions && topbarActions.closest(".topbar-actions-wrap");
    const shellApp = document.querySelector(".app");
    const sidebarInerted = new Set();
    const topbarInerted = new Set();
    let sidebarTrigger = null;
    let topbarTrigger = null;
    if (topbarToggle && topbarActions && !topbarActions.textContent.trim()) {
      topbarToggle.hidden = true;
    }
    function setExpanded(buttons, open) {
      buttons.forEach(function (button) { button.setAttribute("aria-expanded", open ? "true" : "false"); });
    }
    function firstFocusable(root) {
      return root && root.querySelector('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])');
    }
    function clearManagedInert(nodes) {
      nodes.forEach(function (node) { node.inert = false; });
      nodes.clear();
    }
    function inertAppSiblings(excluded, managed) {
      if (!shellApp) return;
      Array.from(shellApp.children).forEach(function (child) {
        if (excluded.indexOf(child) >= 0) return;
        if (!child.inert) {
          child.inert = true;
          managed.add(child);
        }
      });
    }
    function inertMainSiblings(excluded, managed) {
      if (!main) return;
      Array.from(main.children).forEach(function (child) {
        if (excluded.indexOf(child) >= 0) return;
        if (!child.inert) {
          child.inert = true;
          managed.add(child);
        }
      });
    }
    function closeSidebar(restore) {
      if (sidebar) sidebar.classList.remove("open");
      if (overlay) overlay.classList.remove("open");
      setExpanded(navToggles, false);
      clearManagedInert(sidebarInerted);
      if (restore && sidebarTrigger && sidebarTrigger.focus) sidebarTrigger.focus();
      sidebarTrigger = null;
    }
    function closeTopbarMenu(restore) {
      if (topbarActions) topbarActions.classList.remove("open");
      if (topbarToggle) topbarToggle.setAttribute("aria-expanded", "false");
      if (page) page.inert = false;
      if (sidebar) sidebar.inert = false;
      if (topbar) Array.from(topbar.children).forEach(function (child) { if (child !== topbarWrap) child.inert = false; });
      clearManagedInert(topbarInerted);
      if (restore && topbarTrigger && topbarTrigger.focus) topbarTrigger.focus();
      topbarTrigger = null;
    }
    if (navToggles.length && sidebar && overlay) {
      navToggles.forEach(function (navToggle) {
        navToggle.addEventListener("click", function () {
          const open = !sidebar.classList.contains("open");
          sidebar.classList.toggle("open", open);
          overlay.classList.toggle("open", open);
          setExpanded(navToggles, open);
          if (open) {
            sidebarTrigger = navToggle;
            closeTopbarMenu(false);
            inertAppSiblings([sidebar, overlay], sidebarInerted);
            const target = firstFocusable(sidebar);
            if (target) setTimeout(function () { target.focus(); }, 0);
          } else closeSidebar(true);
        });
      });
      overlay.addEventListener("click", function () { closeSidebar(true); });
      sidebar.addEventListener("click", function (ev) {
        if (ev.target.closest("a")) closeSidebar(false);
      });
    }
    if (topbarToggle && topbarActions) {
      topbarToggle.addEventListener("click", function (ev) {
        ev.stopPropagation();
        const open = !topbarActions.classList.contains("open");
        topbarActions.classList.toggle("open", open);
        topbarToggle.setAttribute("aria-expanded", open ? "true" : "false");
        if (open) {
          topbarTrigger = topbarToggle;
          closeSidebar(false);
          if (page) page.inert = true;
          if (sidebar) sidebar.inert = true;
          if (topbar) Array.from(topbar.children).forEach(function (child) { if (child !== topbarWrap) child.inert = true; });
          inertMainSiblings([topbar], topbarInerted);
          inertAppSiblings([main], topbarInerted);
          const target = firstFocusable(topbarActions);
          if (target) setTimeout(function () { target.focus(); }, 0);
        } else closeTopbarMenu(true);
      });
      document.addEventListener("click", function (ev) {
        if (!ev.target.closest(".topbar-actions-wrap")) closeTopbarMenu(false);
      });
    }
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        closeSidebar(true);
        closeTopbarMenu(true);
      }
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 768) {
        closeSidebar(false);
        closeTopbarMenu(false);
      }
    });
    ensureLeaveGuardDelegate();
  }
  function statusBadge(status) {
    const raw = String(status || "blocked");
    const token = raw.toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40) || "blocked";
    const cls = token === "submission_unknown" ? "unknown" : token;
    return '<span class="badge ' + escapeHtml(cls) + '">' + escapeHtml(statusLabel(raw)) + "</span>";
  }
  const STATUS_LABELS = {
    succeeded: "已完成", completed: "已完成", ok: "已完成", ready: "可以开始",
    pending: "等待中", queued: "等待中", running: "处理中", generating: "处理中",
    failed: "未完成", error: "未完成", retry_error: "未完成", blocked: "需要补充", warn: "需要留意",
    aborted: "已取消", cancelled: "已取消", canceled: "已取消",
    budget_exceeded: "额度不足", stale: "需要更新", lost: "状态丢失",
    request_not_sent: "请求确定未发送", provider_rejected: "Provider 已拒绝",
    submission_unknown: "提交状态未知",
  };
  function statusLabel(status) {
    const raw = String(status || "").toLowerCase();
    return STATUS_LABELS[raw] || "状态待确认";
  }
  function verdictBadge(verdict) {
    if (!verdict) return '<span class="badge no-dot">—</span>';
    const v = String(verdict).toLowerCase();
    const cls = v === "approve" ? "approve" : v === "reject" ? "reject" : "abstain";
    return '<span class="badge ' + cls + '">' + escapeHtml(verdictLabel(v)) + "</span>";
  }
  function verdictLabel(verdict) {
    const labels = { approve: "通过", reject: "驳回", abstain: "待定", failure: "未完成" };
    return labels[String(verdict || "").toLowerCase()] || "状态待确认";
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
    const severityLabels = { ok: "文风稳定", warn: "文风需留意", red: "文风偏离明显", skipped: "文风未检查" };
    const label = (severityLabels[severity] || "文风状态待确认") +
      (severity !== "skipped" && Number.isFinite(score) ? " " + score.toFixed(2) : "");
    return '<span class="badge ' + cls + '">' + escapeHtml(label) + "</span>";
  }
  function styleRewriteBadge(meta) {
    if (!meta || meta.style_drift_unresolved !== true) return "";
    return '<span class="badge warn">文风改写未解决</span>';
  }
  function typeBadge(type) {
    if (type === "novel") return '<span class="badge no-dot badge-novel">小说</span>';
    return '<span class="badge no-dot badge-muted">类型待确认</span>';
  }
  function mutedStatusBadge(status) {
    return '<span class="badge no-dot badge-muted">' + escapeHtml(statusLabel(status)) + "</span>";
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
  function ctaConfig(kind, fallback) {
    const base = CTA_ACTIONS[kind] || {};
    return {
      label: fallback && fallback.label || base.label || "需要处理",
      action: fallback && fallback.cta_action || base.action || "show_diagnostics",
      cta_label: fallback && fallback.cta_label || base.cta_label || "查看诊断",
      hint: base.hint || "请检查当前作品状态后再继续。",
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
        requestNavigation(wsHref("/plan"));
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
        const explicitChapter = Number(btn.getAttribute("data-write-recovery-chapter") || 0);
        openWriteRecovery(explicitChapter || resolveWriteRecoveryChapter(), btn);
        return;
      }
      if (action === "reload") {
        window.location.reload();
        return;
      }
      if (action === "go_jobs") {
        requestNavigation(ws ? wsHref("/jobs") : "/library");
        return;
      }
      if (action === "go_workbench") {
        requestNavigation(ws ? wsHref("/workbench") : "/library");
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
  function resolveWriteRecoveryChapter() {
    if (lastWorkbenchStatus && Number.isInteger(Number(lastWorkbenchStatus.retry_chapter))) {
      return Number(lastWorkbenchStatus.retry_chapter);
    }
    const form = document.getElementById("write-book-form");
    const value = form && form.elements && form.elements.resume_from ? Number(form.elements.resume_from.value) : 0;
    return Number.isInteger(value) && value >= 1 && value <= 9999 ? value : 0;
  }
  function writeRecoveryParams(chapter) {
    const form = document.getElementById("write-book-form");
    const limits = NOVEL_STAGE_LIMITS["write-book"];
    function positiveBounded(name, fallback, maximum) {
      const control = form && form.elements ? form.elements[name] : null;
      const value = control ? Number(control.value) : fallback;
      return Number.isFinite(value) && value > 0 ? Math.min(value, maximum) : fallback;
    }
    return {
      chapter: chapter,
      tier: form && form.elements && form.elements.tier ? form.elements.tier.value || "mid" : "mid",
      budget_cny: positiveBounded("budget_cny", limits.budget_cny, limits.budget_cny),
      timeout_minutes: positiveBounded("timeout_minutes", limits.timeout_minutes, limits.timeout_minutes),
      max_model_requests: Math.floor(positiveBounded("max_model_requests", limits.max_model_requests, limits.max_model_requests)),
    };
  }
  function writeRecoveryStateCopy(state) {
    const copy = {
      not_needed: "这一章当前不需要强制恢复，请刷新页面查看最新评审状态。",
      needs_review: "草稿仍在等待处理，但不是重试耗尽状态；请先查看评审意见。",
      busy: "当前作品还有任务正在处理。请等待任务结束或先请求取消，系统不会自动重复提交。",
      reconciliation_required: "上一项写作任务状态无法确认，需要先到任务记录对账；系统不会自动重复提交。",
      blocked: "当前章节不符合安全恢复条件，没有启动新任务。",
    };
    return copy[state] || "恢复资格无法确认，没有启动新任务。";
  }
  async function openWriteRecovery(chapter, trigger) {
    chapter = Number(chapter);
    if (!Number.isInteger(chapter) || chapter < 1 || chapter > 9999) {
      showToast("无法确认需要恢复的章节，请刷新作品状态", "error");
      return;
    }
    setControlBusy(trigger, true, "正在检查");
    let recovery;
    try {
      recovery = await fetchJson(wsUrl("/write-recovery?chapter=" + encodeURIComponent(chapter)));
    } catch (err) {
      showToast("恢复检查失败：" + errTitle(err), "error");
      setControlBusy(trigger, false);
      return;
    }
    setControlBusy(trigger, false);
    const eligible = recovery && recovery.state === "eligible" && typeof recovery.state_fingerprint === "string";
    const params = writeRecoveryParams(chapter);
    let committed = false;
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="write-recovery-title">' +
      '<div class="modal-header" id="write-recovery-title">恢复第 ' + escapeHtml(chapter) + ' 章</div>' +
      '<div class="modal-body">' +
      (eligible
        ? '<p>这一章已有未通过评审的失败稿。你可以先查看内容，再决定是否重新生成。</p>' +
          '<div class="alert warn"><strong>恢复范围只有第 ' + escapeHtml(chapter) + ' 章。</strong>确认后会先归档当前正文、评审和元数据，再创建一个新的写作任务；启用真实生成服务时可能产生费用。</div>' +
          '<p>本次上限：' + escapeHtml(params.max_model_requests) + ' 次模型请求 / ' + escapeHtml(params.budget_cny) + ' 元 / ' + escapeHtml(params.timeout_minutes) + ' 分钟。不会沿用旧任务的确认。</p>'
        : '<div class="alert warn">' + escapeHtml(writeRecoveryStateCopy(recovery && recovery.state)) + '</div>') +
      '<div id="write-recovery-error" role="status" aria-live="polite"></div>' +
      '</div><div class="modal-footer">' +
      (recovery && recovery.draft_available
        ? '<a class="btn btn-secondary" href="' + wsHref("/chapter/" + chapter) + '" target="_blank" rel="noopener">查看失败稿</a>'
        : '') +
      '<button type="button" class="btn btn-ghost" data-modal-close>关闭</button>' +
      (eligible ? '<button type="button" class="btn btn-paid" data-write-recovery-confirm>归档并重新生成本章</button>' : '') +
      '</div></div>';
    const confirm = backdrop.querySelector("[data-write-recovery-confirm]");
    const closeButton = backdrop.querySelector("[data-modal-close]");
    const errorBox = backdrop.querySelector("#write-recovery-error");
    const close = mountModal(backdrop, {
      initialFocus: eligible ? closeButton : closeButton,
      canClose: function () { return !committed; },
    });
    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop || ev.target.hasAttribute("data-modal-close")) close();
    });
    if (!confirm) return;
    confirm.addEventListener("click", async function () {
      if (committed) return;
      committed = true;
      setControlBusy(confirm, true, "正在创建任务");
      closeButton.disabled = true;
      try {
        const payload = Object.assign({}, params, {
          state_fingerprint: recovery.state_fingerprint,
          confirm_archive_and_regenerate: true,
        });
        const data = await postJson(wsUrl("/write-recovery"), payload, {
          headers: {
            "Content-Type": "application/json",
            "X-Write-Recovery-Intent": "archive-and-regenerate-v1",
          },
        });
        committed = false;
        close();
        showToast("已创建第 " + chapter + " 章恢复任务", "info");
        const box = document.getElementById("write-book-status");
        const submit = document.getElementById("write-book-submit");
        if (pageKind === "workbench") {
          setWorkbenchMutationLock(true);
          renderWorkbenchHydration("running", { job_id: data.job_id, step: "write-book", status: "pending" });
        }
        if (box && data.job_id) {
          await pollJob(data.job_id, box, submit, async function () {
            if (pageKind === "workbench") await refreshWorkbench();
            if (pageKind === "continue") {
              await refreshReadiness();
              await refreshRecentJobsSidebar();
            }
          });
        }
      } catch (err) {
        committed = false;
        closeButton.disabled = false;
        setControlBusy(confirm, false);
        const recoveryCode = err && err.payload && err.payload.code;
        if (recoveryCode && FRONT_ERROR_CATALOG[recoveryCode]) {
          // A 409 means the confirmation snapshot is no longer actionable.
          // Keep this modal's submit disabled: the user must close it and
          // re-check current state instead of repeatedly hitting the same
          // stale/busy admission decision.
          err.code = recoveryCode;
          confirm.disabled = true;
        }
        errorBox.innerHTML = renderErrorCard(err);
      }
    });
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
    requestNavigation(ws ? (wsHref("/workbench") + "#" + cardId) : "/library");
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
    submission_unknown: { code: "submission_unknown", title: "模型响应超时，结果未确认", cause: "为避免重复生成，系统没有自动重试。请回到工作台核对是否出现新草稿；确认没有后，再由你决定是否重新开始。", actions: [{ label: "回到工作台核对", action: "go_workbench" }] },
    provider_unavailable: { code: "provider_unavailable", title: "模型服务暂时不可用", cause: "本次生成没有完成。请稍后再试，或在设置中更换模型连接。", actions: [{ label: "回到工作台", action: "go_workbench" }] },
    request_limit_exhausted: { code: "request_limit_exhausted", title: "模型请求次数已达上限", cause: "任务已停止，不会继续请求。请缩小生成范围或调整上限后再开始。", actions: [{ label: "调整生成设置", action: "go_workbench" }] },
    context_too_large: { code: "context_too_large", title: "本次输入内容过长", cause: "模型无法接收当前上下文。请缩小生成范围或精简素材后再开始。", actions: [{ label: "调整生成设置", action: "go_workbench" }] },
    job_timeout: { code: "job_timeout", title: "任务达到最长等待时间", cause: "任务已停止，不会继续提交模型请求。请调整最长等待时间后再开始。", actions: [{ label: "调整生成设置", action: "go_workbench" }] },
    generation_failed: { code: "generation_failed", title: "生成过程未完成", cause: "当前内容已保留。请回到工作台检查设置，再由你决定是否重新开始。", actions: [{ label: "回到工作台", action: "go_workbench" }] },
    response_validation_failed: { code: "response_validation_failed", title: "模型返回格式无法验证", cause: "系统已停止后续模型请求，并保留现有内容。请检查模型兼容性后再决定是否重新开始。", actions: [{ label: "回到工作台", action: "go_workbench" }] },
    accounting_unavailable: { code: "accounting_unavailable", title: "本次费用记录不可用", cause: "系统已停止后续模型请求，避免在无法核算额度时继续生成。已有内容会保留。", actions: [{ label: "回到工作台", action: "go_workbench" }] },
    task_failed: { code: "task_failed", title: "任务未完成", cause: "当前内容已保留。请回到对应工作台检查状态后再决定。", actions: [{ label: "回到工作台", action: "go_workbench" }] },
    write_recovery_busy: { code: "write_recovery_busy", title: "当前作品仍有任务在处理", cause: "没有创建新的恢复任务。请先等待现有任务结束，或到任务页请求取消并确认终态。", actions: [{ label: "去任务页", action: "go_jobs" }] },
    write_recovery_reconciliation_required: { code: "write_recovery_reconciliation_required", title: "上一项写作任务需要先对账", cause: "系统无法确认上一项付费写作是否已提交，因此没有重复生成。请先到任务页核对状态。", actions: [{ label: "去任务页", action: "go_jobs" }] },
    write_recovery_state_changed: { code: "write_recovery_state_changed", title: "章节状态已经变化", cause: "没有归档或生成任何内容。请关闭窗口并刷新页面，再按最新状态重新检查。", actions: [{ label: "刷新状态", action: "reload" }] },
  };
  function _normalizeErrorCard(p) {
    if (p && p.payload && p.payload.card) return p.payload.card;
    if (p && p.card) return p.card;
    if (p && p.code && FRONT_ERROR_CATALOG[p.code]) return FRONT_ERROR_CATALOG[p.code];
    return {
      code: "client_error",
      title: "操作没有完成",
      cause: "当前内容已保留。请检查页面提示后重试；如果问题持续出现，可刷新页面再查看任务记录。",
      actions: [], trace_id: "", technical: "",
    };
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
      "</div>";
  }
  // iter063 A2: prefer the backend card's friendly title for one-line error
  // toasts. The `error` field may still carry the raw exception text for
  // back-compat (iter062 4xx/FNF convention), so reach into the card first.
  function errTitle(err) {
    if (err && err.payload && err.payload.card && err.payload.card.title) return err.payload.card.title;
    if (err && err.card && err.card.title) return err.card.title;
    if (err && err.code && FRONT_ERROR_CATALOG[err.code]) return FRONT_ERROR_CATALOG[err.code].title;
    const raw = err && err.payload && err.payload.error;
    return "操作没有完成";
  }
  // Translate readiness codes into bounded user copy. Unknown codes fail
  // closed instead of exposing enum names, exception types, or path fragments.
  function readinessReasonText(code) {
    const raw = String(code || "");
    var k = raw.split(":")[0];
    if (raw.startsWith("chapter_plan:") || raw.includes("plan_item_missing")) k = "chapter_plan_missing";
    else if (raw.startsWith("preflight:")) k = "preflight_failed";
    else if (raw.startsWith("extraction:start_window_unextracted") || raw.includes("extraction coverage gap before start point")) k = "extraction_coverage_missing";
    else if (raw.includes("stale debate outline")) k = "outline_stale";
    else if (raw.startsWith("outline_severe_drift")) k = "outline_drift_severe";
    else if (raw.includes("retry_exhausted") || raw.includes("existing_output_not_strict_approved")) k = "retry_exhausted";
    else if (raw.startsWith("story_memory_")) k = "story_memory_stale";
    else if (raw.startsWith("foreshadowing_must_resolve_overdue") || raw.startsWith("foreshadowing_gate_error")) k = "foreshadowing_overdue";
    var cfg = CTA_ACTIONS[k];
    if (cfg && cfg.label) return cfg.label;
    var named = {
      overview_error: "概览数据读取失败",
      readiness_error: "续写入口检查失败",
      chapter_plan_invalid: "章节计划文件损坏",
      preflight_failed: "工程预检未通过",
    };
    return named[k] || "有一项续写条件需要补充";
  }
  function readinessWarningText(code) {
    const raw = String(code || "");
    if (raw.startsWith("preflight:")) return "运行检查有一项建议需要确认";
    if (raw.startsWith("outline_")) return "大纲与近期剧情存在差异，建议先复核";
    if (raw.startsWith("extraction:")) return "起点附近的设定提取待补充";
    if (raw.startsWith("rolling_summary_gap:")) return "部分前文摘要待补充";
    if (raw.startsWith("entity_proposal_gap:")) return "部分实体变更待确认";
    if (raw.startsWith("chapter_")) return "有一章需要额外确认";
    if (raw.startsWith("foreshadowing_boundary_overdue:")) return "有伏笔接近或超过建议回收时间";
    if (raw.includes("knowledge_index")) return "作品知识库索引待补充，可能影响起点过滤";
    return "有一项建议需要确认";
  }
  function groupedReadinessHtml(items, textFn, excludeKind) {
    const groups = new Map();
    const excludeMessage = excludeKind ? ctaConfig(excludeKind, {}).label : "";
    (Array.isArray(items) ? items : []).forEach(function (item) {
      const rawKind = String(item || "").split(":")[0];
      const message = textFn(item);
      if (excludeKind && (rawKind === excludeKind || message === excludeMessage)) return;
      const current = groups.get(message) || { message: message, count: 0 };
      current.count += 1;
      groups.set(message, current);
    });
    return Array.from(groups.values()).map(function (group) {
      return escapeHtml(group.message) + (group.count > 1 ? "（共 " + group.count + " 项）" : "");
    }).join("<br>");
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

  const toastRegistry = new Map();
  function showToast(msg, kind, options) {
    const stack = document.getElementById("toast-stack");
    if (!stack) return;
    const opts = options || {};
    const key = String(kind || "info") + "\u0000" + String(msg || "");
    const existing = toastRegistry.get(key);
    if (existing && existing.el && existing.el.parentNode) {
      existing.count += 1;
      existing.text.textContent = msg + " ×" + existing.count;
      clearTimeout(existing.timer);
      existing.timer = setTimeout(function () { removeToast(existing.el); }, 5000);
      stack.appendChild(existing.el);
      return;
    }
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
    const record = { el: el, text: text, count: 1, key: key, timer: null };
    toastRegistry.set(key, record);
    while (stack.children.length > 3) removeToast(stack.firstElementChild, true);
    record.timer = setTimeout(function () { removeToast(el); }, 5000);
  }
  function removeToast(el, immediate) {
    if (!el || !el.parentNode) return;
    const record = Array.from(toastRegistry.values()).find(function (item) { return item.el === el; });
    if (record) {
      clearTimeout(record.timer);
      toastRegistry.delete(record.key);
    }
    if (immediate) { el.remove(); return; }
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
      // Locked tabs are inert — no activation/route.
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
    const search = document.getElementById("library-search");
    const live = document.getElementById("library-status");
    if (!shelf) return;
    shelf.innerHTML = skeleton(4);
    try {
      const data = await fetchJson("/api/workspaces/overview");
      const items = Array.isArray(data.workspaces) ? data.workspaces.filter(function (item) {
        return item && typeof item === "object" && typeof item.name === "string";
      }) : [];
      if (!items.length) {
        shelf.innerHTML = emptyState(
          "书架还是空的",
          shelf.dataset.empty || "从一句话开新书或导入小说续写，开始你的第一部作品。",
          '<a class="btn btn-primary" href="/wizard?type=novel">创建小说作品</a>'
        );
        if (stats) stats.innerHTML = "";
        if (live) live.textContent = "当前没有作品。";
        return;
      }
      const novels = items.filter((w) => w.type === "novel").length;
      const unknownTypes = items.length - novels;
      if (stats) {
        stats.innerHTML = [
          '<span class="badge no-dot">共 ' + items.length + " 部作品</span>",
          '<span class="badge no-dot badge-novel">小说 ' + novels + "</span>",
          unknownTypes ? '<span class="badge no-dot badge-muted">类型待确认 ' + unknownTypes + "</span>" : "",
        ].join("");
      }
      function renderItems(query) {
        const normalized = String(query || "").trim().toLocaleLowerCase("zh-CN");
        const visible = normalized ? items.filter(function (item) {
          return item.name.toLocaleLowerCase("zh-CN").includes(normalized);
        }) : items;
        shelf.innerHTML = visible.length ? visible.map(renderWorkspaceCard).join("") : emptyState(
          "没有找到作品", "换一个名称试试，现有作品没有被修改。", ""
        );
        if (live) live.textContent = "显示 " + visible.length + " 部作品。";
      }
      renderItems("");
      if (search) search.addEventListener("input", function () { renderItems(search.value); });
    } catch (err) {
      shelf.innerHTML = publicLoadError(
        "作品列表没有读取成功",
        "已有本地作品不会因此改变。可以重新加载，或继续创建新作品。",
        '<button type="button" class="btn btn-secondary" data-cta-action="reload">重新加载</button>' +
        '<a class="btn btn-primary" href="/wizard?type=novel">创建小说作品</a>'
      );
      if (live) live.textContent = "作品列表没有读取成功。";
    }
  }
  function publicLoadError(title, explanation, actions) {
    return '<div class="error-card" role="alert"><div class="error-card-head">' +
      '<span class="error-card-icon" aria-hidden="true">!</span><div class="error-card-copy">' +
      '<p class="error-card-title">' + escapeHtml(title) + '</p>' +
      '<p class="error-card-cause">' + escapeHtml(explanation) + '</p></div></div>' +
      '<div class="cluster error-card-actions">' + (actions || "") + '</div></div>';
  }
  function safePublicCount(value) {
    return typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;
  }
  function safeOptionalCount(value) {
    const number = finiteStyleNumber(value);
    return number != null && number >= 0 ? Math.floor(number) : null;
  }
  function publicDateLabel(value) {
  if (typeof value !== "string" || !/^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}$/.test(value)) return "尚无更新记录";
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return "尚无更新记录";
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"
    }).format(date);
  }
  function renderWorkspaceCard(w) {
    const type = w.type === "novel" ? "novel" : "unknown";
    const readiness = w.readiness && typeof w.readiness === "object" ? w.readiness : {};
    const status = type === "unknown" ? "unknown" : readiness.status;
    const progress = type === "unknown" ? "作品类型待确认" : statusLabel(status);
    const detail = type === "unknown" ? "请重新加载；确认前不会打开作品" :
      (safePublicCount(w.draft_count) ? "已有 " + safePublicCount(w.draft_count) + " 章续写草稿" :
        (safePublicCount(w.chapter_count) ? "已导入 " + safePublicCount(w.chapter_count) + " 章原文" : "等待准备故事内容"));
    const url = "/w/" + encodeURIComponent(w.name) + "/";
    const action = type === "unknown"
      ? '<button type="button" class="btn btn-secondary" data-cta-action="reload">重新加载</button>'
      : '<a class="btn btn-primary" href="' + url + '">打开作品</a>';
    return (
      '<article class="public-work-card">' +
      '<div><p class="eyebrow ornament">作品</p><h2>' + escapeHtml(w.name) + '</h2>' +
      '<div class="cluster" style="margin-top:8px">' + typeBadge(type) + statusBadge(status || "unknown") + '</div></div>' +
      '<dl class="public-work-meta">' +
      '<div><dt>最近更新</dt><dd>' + escapeHtml(publicDateLabel(w.updated_at)) + '</dd></div>' +
      '<div><dt>当前进度</dt><dd>' + escapeHtml(progress) + '</dd></div>' +
      '<div><dt>内容概况</dt><dd>' + escapeHtml(detail) + '</dd></div>' +
      '<div><dt>作品类型</dt><dd>' + (type === "novel" ? "小说" : "待确认") + '</dd></div>' +
      '</dl>' +
      '<div class="cluster public-work-actions">' + action + '</div>' +
      '</article>'
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

  // ===== page: workspace overview =========================================
  let overviewCreationMode = "continuation";
  async function initWorkspaceOverview() {
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
    loadOverviewRecentChapter();
    loadOverviewDetails();
    initDeleteWorkspace();
  }
  async function loadOverviewRecentChapter() {
    const box = document.getElementById("overview-recent-chapter");
    if (!box) return;
    box.innerHTML = skeleton(1);
    try {
      const data = await fetchJson(wsUrl("/drafts"));
      const drafts = Array.isArray(data.drafts) ? data.drafts.filter(function (draft) {
        const chapter = finiteStyleNumber(draft && draft.chapter);
        return chapter != null && Number.isInteger(chapter) && chapter > 0 && draft.variant !== "partial";
      }) : [];
      drafts.sort(function (a, b) { return Number(b.chapter) - Number(a.chapter); });
      if (!drafts.length) {
        box.innerHTML = emptyState(
          overviewCreationMode === "greenfield" ? "还没有保存正文" : "还没有保存续写章节",
          "完成正文阶段后，最近保存的章节会显示在这里。",
          '<a class="btn btn-primary" href="' + wsHref("/workbench") + '">进入创作工作台</a>'
        );
        return;
      }
      const chapter = Number(drafts[0].chapter);
      box.innerHTML = '<div class="card"><div class="card-body section-title"><div><p class="eyebrow ornament">最近保存</p><h3>第 ' + chapter + ' 章</h3><p class="muted">内容来自已保存正文。</p></div><a class="btn btn-primary" href="' + wsHref("/chapter/" + chapter) + '">打开章节</a></div></div>';
    } catch (err) {
      box.innerHTML = publicLoadError("最近章节没有读取成功", "已保存内容不受影响，可从章节列表继续查找。", '<a class="btn btn-secondary" href="' + wsHref("/chapters") + '">打开章节列表</a>');
    }
  }
  function renderOverview(item) {
    const readiness = item.readiness && typeof item.readiness === "object" ? item.readiness : {};
    const greenfield = item.creation_mode === "greenfield";
    overviewCreationMode = greenfield ? "greenfield" : "continuation";
    const intro = document.getElementById("overview-mode-intro");
    if (intro) intro.textContent = greenfield
      ? "按原创开书阶段继续准备设定、大纲、细纲与正文。"
      : "从已导入原文选择起点，按续写阶段继续创作。";
    const stage = item.workbench_stage || (item.workbench && item.workbench.stage) || "prepare";
    const finalStage = stage === "write" || stage === "done";
    const statusEl = document.getElementById("overview-status-badge");
    if (statusEl) statusEl.innerHTML = statusBadge(finalStage ? (readiness.status || "blocked") : "pending");
    const summary = document.getElementById("overview-summary");
    if (summary) {
      summary.innerHTML =
        '<div class="tile"><span class="k">' + (greenfield ? '创作素材' : '原文章节') + '</span><span class="v">' + safePublicCount(item.chapter_count) + '<span class="sub"> ' + (greenfield ? '项' : '章') + '</span></span></div>' +
        '<div class="tile"><span class="k">最近保存</span><span class="v">' + safePublicCount(item.draft_count) + '<span class="sub"> 章正文</span></span></div>' +
        '<div class="tile"><span class="k">评审通过</span><span class="v">' +
        safePublicCount(item.review_accepted) + '<span class="sub"> / ' + safePublicCount(item.review_total) + '</span></span></div>' +
        '<div class="tile"><span class="k">下一章准备</span><span class="v metric-small">' +
        (finalStage ? (readiness.status === "ready" ? "可以开始" : readiness.status === "warn" ? "需要留意" : readiness.status === "blocked" ? "需要补充" : "状态待确认") : "继续准备") + "</span></div>";
    }
    const nextAction = document.getElementById("overview-next-action");
    if (nextAction) {
      const status = readiness.status || "blocked";
      const blockers = readiness.blockers || [];
      const start = item.start_point && item.start_point.has_start_point
        ? "已设置"
        : "未设置";
      let hint = "";
      let cta = '<a class="btn btn-primary" href="/w/' + encodeURIComponent(ws) + '/workbench">进入创作工作台</a>';
      if (!finalStage) {
        const stageHints = {
          start: "先选择续写起点",
          prepare: greenfield ? "下一步：准备原创设定" : "下一步：整理续写设定",
          outline: "下一步：生成故事大纲",
          plan: "下一步：生成分章细纲",
        };
        hint = stageHints[stage] || "继续完成创作准备";
        if (stage === "start") cta = '<a class="btn btn-primary" href="/w/' + encodeURIComponent(ws) + '/continue">选择续写起点</a>';
      } else if (status === "ready") {
        hint = greenfield ? "一切就绪，可以开始写正文。" : "一切就绪，可以续写下一章。";
      } else if (status === "warn") {
        hint = "可以续写，但有可关注的提示。";
      } else {
        hint = blockers.length ? readinessReasonText(blockers[0]) : "存在阻断项，需先处理。";
        cta = '<a class="btn btn-primary" href="/w/' + encodeURIComponent(ws) + '/workbench">进入创作工作台</a>';
      }
      nextAction.innerHTML =
        '<p class="eyebrow ornament">下一步</p>' +
        '<h2>' + escapeHtml(hint) + '</h2>' +
        '<p class="hint">' + (greenfield ? '创作模式：原创开书' : '续写起点：' + escapeHtml(start)) + '　·　章节计划：' + safePublicCount((item.plan || {}).chapters) + ' 章</p>' +
        '<div class="cta-row">' + cta + '</div>';
    }
    const blockersBox = document.getElementById("overview-blockers");
    if (blockersBox) {
      const allBlockers = readiness.blockers || [];
      const blockers = finalStage ? allBlockers : allBlockers.filter(function (item) {
        const raw = String(item || "");
        return !(
          raw === "start_point_missing" || raw === "kb_missing" ||
          raw.startsWith("extraction:start_window_unextracted") ||
          raw.startsWith("outline_missing") || raw.startsWith("chapter_plan:") ||
          raw.includes("plan_item_missing")
        );
      });
      const warnings = readiness.warnings || [];
      const parts = [];
      if (blockers.length) {
        parts.push(
          '<div class="alert error"><strong>阻断：</strong>' +
          groupedReadinessHtml(blockers, readinessReasonText, "") + "</div>"
        );
      }
      if (warnings.length) {
        parts.push(
          '<div class="alert warn"><strong>警示：</strong>' +
          groupedReadinessHtml(warnings, readinessWarningText, "") + "</div>"
        );
      }
      blockersBox.innerHTML = parts.join("") ||
        '<div class="alert info">' + (finalStage ? '当前没有待处理问题，可以继续创作下一章。' : '当前阶段没有安全阻断，请按上方下一步继续准备。') + '</div>';
    }
  }
  async function loadOverviewDetails() {
    const statusBox = document.getElementById("overview-detail-status");
    const costBox = document.getElementById("overview-detail-cost");
    if (statusBox) {
      statusBox.innerHTML = skeleton(4);
      fetchJson(wsUrl("/status"))
        .then((d) => { statusBox.innerHTML = renderNovelStatusDetails(d); })
        .catch((e) => { statusBox.innerHTML = renderErrorCard(e); });
    }
    if (costBox) {
      costBox.innerHTML = skeleton(3);
      fetchJson(wsUrl("/cost"))
        .then((d) => { costBox.innerHTML = renderNovelUsageDetails(d); })
        .catch((e) => { costBox.innerHTML = renderErrorCard(e); });
    }
  }
  function renderNovelStatusDetails(data) {
    const rows = [
      ["原文整理", data && data.normalize && data.normalize.done ? "已完成" : "未开始"],
      ["章节切分", data && data.split && data.split.done ? "已完成" : "未开始"],
      ["设定整理", data && data.compress && data.compress.done ? "已完成" : "未开始"],
      ["故事大纲", data && data.debate && data.debate.done ? "已完成" : "未开始"],
      ["续写草稿", Number(data && data.write && data.write.drafts || 0) + " 章"],
      ["评审记录", Number(data && data.review && data.review.review_reports || 0) + " 份"],
    ];
    return '<div class="kv-list compact">' + rows.map(function (row) {
      return '<div class="k">' + row[0] + '</div><div class="v">' + escapeHtml(row[1]) + '</div>';
    }).join("") + '</div>';
  }
  function renderNovelUsageDetails(data) {
    const rows = [
      ["原文章节", Number(data && data.chapters || 0) + " 章"],
      ["原文字数", Number(data && data.source_chars || 0) + " 字"],
      ["已记录生成调用", Number(data && data.llm_logged_calls || 0) + " 次"],
      ["设定抽取任务", Number(data && data.extract_calls || 0) + " 次"],
    ];
    return '<div class="kv-list compact">' + rows.map(function (row) {
      return '<div class="k">' + row[0] + '</div><div class="v">' + escapeHtml(row[1]) + '</div>';
    }).join("") + '</div>';
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
      if (typeof opts.canClose === "function" && !opts.canClose()) return;
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
    const app = document.querySelector(".app");
    if (app && app.classList.contains("ui-public")) backdrop.classList.add("ui-public");
    if (app && app.classList.contains("ui-novel")) backdrop.classList.add("ui-novel");
    document.body.appendChild(backdrop);
    document.addEventListener("keydown", onKeyDown);
    _activeModalTeardown = close;
    setTimeout(function () {
      const target = opts.initialFocus || focusables()[0];
      if (target && typeof target.focus === "function") target.focus();
    }, 0);
    return close;
  }
  function confirmPaidAction(options) {
    options = options || {};
    return new Promise(function (resolve) {
      let settled = false;
      const backdrop = document.createElement("div");
      backdrop.className = "modal-backdrop";
      backdrop.innerHTML =
        '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="paid-action-title">' +
        '<div class="modal-header" id="paid-action-title">' + escapeHtml(options.title || "确认生成") + '</div>' +
        '<div class="modal-body"><p>' + escapeHtml(options.action || "将开始一次生成操作。") + '</p>' +
        '<div class="alert warn">启用真实生成服务时，本次操作可能使用人民币额度；离线模式不会使用真实额度。</div>' +
        '<p>' + escapeHtml(options.preservation || "已有内容会保留；开始后可在任务记录中查看进度或请求取消。") + '</p>' +
        (options.scope ? '<p><strong>本次范围：</strong>' + escapeHtml(options.scope) + '</p>' : '') +
        '</div><div class="modal-footer">' +
        '<button type="button" class="btn btn-ghost" data-modal-close>取消</button>' +
        '<button type="button" class="btn btn-paid" data-paid-action-confirm>确认并开始</button>' +
        '</div></div>';
      function finish(value) {
        if (settled) return;
        settled = true;
        close();
        resolve(value);
      }
      const close = mountModal(backdrop, {
        initialFocus: backdrop.querySelector("[data-modal-close]"),
        onClose: function () { if (!settled) { settled = true; resolve(false); } },
      });
      backdrop.addEventListener("click", function (ev) {
        if (ev.target === backdrop || ev.target.hasAttribute("data-modal-close")) finish(false);
      });
      backdrop.querySelector("[data-paid-action-confirm]").addEventListener("click", function () { finish(true); });
    });
  }
  function paidLimitScope(prefix, limits) {
    limits = limits || {};
    const parts = [];
    if (prefix) parts.push(prefix);
    if (Number(limits.max_model_requests) > 0) parts.push("最多 " + Number(limits.max_model_requests) + " 次模型请求");
    if (Number(limits.budget_cny) > 0) parts.push("额度上限 " + Number(limits.budget_cny) + " 元");
    if (Number(limits.timeout_minutes) > 0) parts.push("最长等待 " + Number(limits.timeout_minutes) + " 分钟");
    return parts.join("；");
  }
  window.uiConfirmPaidAction = confirmPaidAction;

  function showDeleteModal(name) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">' +
      '<div class="modal-header" id="modal-title">删除作品 《' + escapeHtml(name) + '》</div>' +
      '<div class="modal-body">' +
      '<p>这一步会把整个作品移到回收站，已有内容会保留，之后仍可恢复。</p>' +
      '<p>为了避免误删，请在下方输入 <strong>' + escapeHtml(name) + '</strong> 以确认。</p>' +
      '<div class="field">' +
      '<label>作品名称</label>' +
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
      setControlBusy(confirmBtn, true, "正在移除");
      errBox.innerHTML = '<div class="alert info">正在移到回收站；已有内容会保留。</div>';
      try {
        const data = await postJson("/api/workspace/" + encodeURIComponent(name) + "/delete",
          { confirm: name });
        window.setPendingToastAndNavigate(
          { kind: "info", msg: "已将《" + name + "》移到回收站" },
          "/library"
        );
      } catch (err) {
        errBox.innerHTML = renderErrorCard(err);
        setControlBusy(confirmBtn, false);
      }
    });
  }

  // iter071: map internal step ids (jobs.py STEP_HANDLERS keys) to the Chinese
  // the user should actually see — raw ids like "write-book" must never leak
  // into user-facing copy (the leave-guard modal surfaced this). Unknown ids
  // fail closed for unknown ids so a new backend step cannot leak into UI.
  const STEP_LABELS = {
    "normalize": "规范化原文", "split": "切分章节", "extract": "抽取设定",
    "compress": "构建知识库", "bootstrap": "生成实体提案", "apply-bootstrap": "应用实体提案",
    "debate": "生成大纲", "plan-chapters": "规划章节", "write-book": "续写正文",
    "review-chapter": "评审章节", "draft-once-dev": "试写一章",
    "auto-pipeline": "导入并初始化作品", "auto-pipeline-greenfield": "一键开新书",
    "prepare-greenfield": "准备开新书", "prepare-import": "整理导入原文",
    "rebuild-for-start": "重建续写底座", "expand-premise": "扩写设定",
    "extract-style": "提取文风",
  };
  function stepLabel(step) {
    return STEP_LABELS[step] || "未识别步骤";
  }
  // iter166: ``job.step`` is a stable top-level job id, while
  // ``job.current_step`` is a progress token and may contain bounded dynamic
  // suffixes (chapter ids, proposal names, retry numbers).  Never feed the
  // latter through STEP_LABELS: that produced the user-visible
  // "未识别步骤" bug and risked exposing internal suffixes.  Recognise only
  // documented exact tokens/prefixes and otherwise fall back to the safe
  // top-level label (or the generic running copy).
  function currentStepLabel(currentStep, jobStep, status) {
    const terminal = String(status || "").toLowerCase();
    if (["succeeded", "failed", "blocked", "aborted", "budget_exceeded", "lost"].indexOf(terminal) >= 0) {
      return statusLabel(terminal);
    }
    const raw = String(currentStep || "");
    const exact = {
      expand: "扩写故事设定", normalize: "规范化原文", split: "切分章节",
      extract: "抽取章节设定", compress: "构建作品知识库",
      bootstrap: "生成实体提案", "apply-bootstrap": "应用实体提案",
      debate: "生成故事大纲", "debate-decisions": "整理大纲决策",
      "debate-ballot": "汇总大纲投票", "debate-outline": "形成故事大纲",
      plan: "生成章节细纲", "plan-chapters": "生成章节细纲",
      write: "撰写章节正文", review: "评审章节", polish: "润色章节",
      "sync-meta": "整理评审结果", done: "完成当前任务",
      cancelled: "正在取消", timeout: "已到最长等待时间", blocked: "需要补充内容",
    };
    if (exact[raw]) return exact[raw];
    if (raw.startsWith("extract:")) return "抽取章节设定";
    if (raw.startsWith("compress:")) return "构建作品知识库";
    if (raw.startsWith("bootstrap:")) return "生成实体提案";
    if (raw.startsWith("debate-") || raw.startsWith("debate:")) return "生成故事大纲";
    if (/^chapter-\\d+$/.test(raw)) return "准备章节正文";
    if (/^chapter-\\d+(?:\\/retry-\\d+)?\\/(?:write-attempt-\\d+|review-attempt-\\d+|review-done-attempt-\\d+|polish|style-rewrite|style-rewrite-review|finalize|sync-meta|caveat_continue)$/.test(raw)) {
      if (/\\/review(?:-done)?-attempt-\\d+$/.test(raw) || raw.endsWith("/style-rewrite-review")) return "评审章节";
      if (raw.endsWith("/polish") || raw.endsWith("/style-rewrite")) return "润色章节";
      if (raw.endsWith("/sync-meta") || raw.endsWith("/finalize")) return "整理评审结果";
      return "撰写章节正文";
    }
    const parent = STEP_LABELS[String(jobStep || "")];
    return parent || "任务处理中";
  }
  const PAID_NOVEL_JOB_STEPS = new Set([
    "extract", "compress", "bootstrap", "debate", "plan-chapters", "write-book",
    "review-chapter", "draft-once-dev", "auto-pipeline-greenfield",
    "auto-pipeline", "prepare-greenfield", "rebuild-for-start", "expand-premise", "extract-style",
  ]);
  function isPaidNovelJobStep(step) {
    return PAID_NOVEL_JOB_STEPS.has(String(step || ""));
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
  const dirtyEditorRegistry = new Map();
  function registerDirtyEditor(key, editor) {
    dirtyEditorRegistry.set(key, editor);
    return function () { dirtyEditorRegistry.delete(key); };
  }
  function dirtyEditors() {
    return Array.from(dirtyEditorRegistry.values()).filter(function (editor) {
      try { return !!editor.isDirty(); } catch (e) { return false; }
    });
  }
  // A successful response acknowledges only the values actually submitted.
  function captureEditSnapshot(root, controls) {
    const fields = controls || (root.matches && root.matches("input,textarea,select")
      ? [root] : Array.from(root.querySelectorAll("input,textarea,select")));
    return { root: root, fields: fields, explicit: !!controls, values: fields.map(function (field) { return field.value; }) };
  }
  function acknowledgeEditSnapshot(snapshot) {
    if (!snapshot.root.isConnected || snapshot.fields.some(function (field) { return !field.isConnected; })) return false;
    const current = snapshot.explicit ? snapshot.fields : captureEditSnapshot(snapshot.root).fields;
    const changed = current.length !== snapshot.fields.length || current.some(function (field, index) {
      return field !== snapshot.fields[index] || field.value !== snapshot.values[index];
    });
    if (changed) {
      snapshot.root.dataset.dirty = "1";
      snapshot.fields.forEach(function (field) { field.dataset.dirty = "1"; });
      showToast("已保存提交时的内容；仍有新的修改尚未保存", "warn");
      return false;
    }
    delete snapshot.root.dataset.dirty;
    snapshot.fields.forEach(function (field) { delete field.dataset.dirty; });
    return true;
  }
  async function clickAndAwaitClean(button, isDirty) {
    if (!button || button.disabled) return false;
    button.click();
    for (let i = 0; i < 600; i++) {
      await new Promise(function (resolve) { setTimeout(resolve, 50); });
      if (!isDirty()) return true;
      if (i > 1 && !button.disabled) return false;
    }
    return false;
  }
  window.addEventListener("beforeunload", function (event) {
    if (!dirtyEditors().length) return;
    event.preventDefault();
    event.returnValue = "";
  });
  function classifyNavigation(href) {
    const target = new URL(href || window.location.href, window.location.href);
    const current = new URL(window.location.href);
    if (target.origin === current.origin && target.pathname === current.pathname && target.search === current.search) return "same-document";
    const prefix = window.WORKSPACE_NAME ? "/w/" + encodeURIComponent(window.WORKSPACE_NAME) + "/" : "";
    if (target.origin === current.origin && prefix && (target.pathname + "/").indexOf(prefix) === 0) return "same-workspace";
    if (target.origin === current.origin && target.pathname.indexOf("/w/") === 0) return "switch-workspace";
    return "leave-workspace";
  }
  function navigateNow(href) { window.location.href = href; }
  function ensureLeaveGuardDelegate() {
    if (leaveGuardDelegateBound) return;
    leaveGuardDelegateBound = true;
    document.addEventListener("click", function (ev) {
      const link = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
      if (!link) return;
      if (!window.WORKSPACE_NAME) return;  // no workspace context → nothing to guard
      if (link.target === "_blank" || link.hasAttribute("download")) return;
      if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button === 1) return;
      const href = link.getAttribute("href") || "/";
      ev.preventDefault();  // synchronous — must precede the async check
      requestNavigation(href);
    });
  }
  function guardedNavigate(href) {
    requestNavigation(href);
  }
  function requestNavigation(href) {
    if (leaveGuardModalOpen) return;
    const kind = classifyNavigation(href);
    if (kind === "same-document") { navigateNow(href); return; }
    const dirty = dirtyEditors();
    if (dirty.length) {
      leaveGuardModalOpen = true;
      showDirtyLeaveModal(href, kind, dirty);
      return;
    }
    continueNavigation(href, kind);
  }
  function continueNavigation(href, kind) {
    if (kind === "same-document" || kind === "same-workspace") { navigateNow(href); return; }
    const seq = ++leaveGuardSeq;
    checkLeaveGuard(href, seq);
  }
  function showDirtyLeaveModal(href, kind, editors) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="dirty-leave-title">' +
      '<div class="modal-header" id="dirty-leave-title">还有未保存的修改</div>' +
      '<div class="modal-body"><p>' + escapeHtml(editors.map(function (editor) { return editor.label; }).join('、')) +
      '尚未保存。可以继续编辑、放弃修改，或保存全部后继续。</p>' +
      '<div id="dirty-leave-error" role="status" aria-live="polite"></div></div>' +
      '<div class="modal-footer modal-footer-equal">' +
      '<button type="button" class="btn btn-ghost" data-modal-close>继续编辑</button>' +
      '<button type="button" class="btn btn-danger" data-discard-dirty>放弃修改</button>' +
      '<button type="button" class="btn btn-primary" data-save-dirty-leave>保存全部并继续</button>' +
      '</div></div>';
    const stayBtn = backdrop.querySelector("[data-modal-close]");
    const discardBtn = backdrop.querySelector("[data-discard-dirty]");
    const saveLeaveBtn = backdrop.querySelector("[data-save-dirty-leave]");
    const errorBox = backdrop.querySelector("#dirty-leave-error");
    const closeModal = mountModal(backdrop, {
      initialFocus: stayBtn,
      onClose: function () {
        leaveGuardModalOpen = false;
        const first = editors[0];
        if (first && first.focus) first.focus();
      },
    });
    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop || ev.target.hasAttribute("data-modal-close")) closeModal();
    });
    discardBtn.addEventListener("click", function () {
      editors.forEach(function (editor) { if (editor.discard) editor.discard(); });
      closeModal();
      continueNavigation(href, kind);
    });
    saveLeaveBtn.addEventListener("click", async function () {
      setControlBusy(saveLeaveBtn, true, "正在保存");
      discardBtn.disabled = true;
      stayBtn.disabled = true;
      const failed = [];
      workbenchBulkSaving = true;
      try {
        for (const editor of editors) {
          let stillDirty = false;
          try { stillDirty = !!editor.isDirty(); } catch (e) { stillDirty = true; }
          if (!stillDirty) continue;
          try { if (!editor.save || !(await editor.save())) failed.push(editor); }
          catch (e) { failed.push(editor); }
        }
      } finally {
        workbenchBulkSaving = false;
      }
      dirtyEditors().forEach(function (editor) { if (failed.indexOf(editor) === -1) failed.push(editor); });
      if (!failed.length) {
        closeModal();
        continueNavigation(href, kind);
        return;
      }
      errorBox.textContent = failed.map(function (editor) { return editor.label; }).join('、') + "没有保存成功；输入仍保留。";
      setControlBusy(saveLeaveBtn, false);
      discardBtn.disabled = false;
      stayBtn.disabled = false;
      saveLeaveBtn.focus();
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
      planPageData = data;
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
    const targetRaw = safeOptionalCount(plan.target_chapters);
    const planRows = Array.isArray(plan.chapters) ? plan.chapters.filter(function (item) { return item && typeof item === "object" && !Array.isArray(item); }) : [];
    const target = targetRaw == null ? (planRows.length || null) : targetRaw;
    // iter 053a: outline↔start-point staleness warning (audit A5).
    const oc = data.outline_consistency || {};
    let outlineWarn = '';
    // iter072 (#8): point Web users at the in-app action ("② 大纲 · 生成大纲" on
    // the workbench) instead of leaking a non-executable CLI command
    // (`debate --force`) they have no terminal to run.
    if (oc.checked && oc.stale) {
      outlineWarn =
        '<div class="alert error" style="margin-top:8px"><strong>大纲需要更新：</strong>' +
        '续写起点已经变化。请回到创作工作台重新生成大纲，再继续使用章节计划。</div>';
    } else if (oc.checked && oc.metadata_missing) {
      outlineWarn =
        '<div class="alert info" style="margin-top:8px">大纲状态需要确认。请回到创作工作台重新生成大纲后再继续。</div>';
    }
    box.innerHTML =
      '<span class="badge no-dot">续写起点 ' + escapeHtml(plan.start_chapter_id || "尚未设置") + '</span>' +
      '<span class="badge no-dot">已写 ' + safePublicCount(drafts.length) + ' / 计划 ' + (target == null ? "状态待确认" : target) + '</span>' +
      outlineWarn;
  }
  let planPageData = null;
  function renderPlanChapters(box, plan, draftChapters, draftVerdicts) {
    if (!box) return;
    const chapters = Array.isArray(plan && plan.chapters) ? plan.chapters.filter(function (item) { return item && typeof item === "object" && !Array.isArray(item); }) : [];
    const arc = typeof (plan && plan.overall_arc) === "string" ? plan.overall_arc.slice(0, 4000) : "";
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
      const no = Number.isSafeInteger(Number(c.chapter_no)) && Number(c.chapter_no) > 0 ? Number(c.chapter_no) : 0;
      if (!no) return "";
      const written = draftSet.has(no);
      const verdict = draftVerdicts && draftVerdicts[String(no)];
      const head =
        '<div class="card-header" style="align-items:flex-start">' +
        '<div><p class="eyebrow ornament">第 ' + escapeHtml(String(c.chapter_no || "?")) + ' 章</p>' +
        '<h3>' + escapeHtml(typeof c.title === "string" ? c.title.slice(0, 160) : "未命名章节") + '</h3></div>' +
        '<div class="cluster">' +
        (written ? '<span class="badge ready">已写</span>' : '<span class="badge no-dot">未写</span>') +
        (written && verdict ? verdictBadge(verdict) : '') +
        '</div></div>';
      const events = (Array.isArray(c.key_events) ? c.key_events.filter(function (item) { return typeof item === "string"; }) : []).map(function (e) {
        return '<li>' + escapeHtml(e) + '</li>';
      }).join("");
      const rels = (Array.isArray(c.relationships_in_play) ? c.relationships_in_play.filter(function (item) { return typeof item === "string"; }) : []).map(function (r) {
        return '<span class="badge no-dot">' + escapeHtml(r) + '</span>';
      }).join(" ");
      const body =
        '<div class="card-body">' +
        (c.opening_scene ? '<p><strong>开场：</strong>' + escapeHtml(c.opening_scene) + '</p>' : '') +
        (events ? '<div><strong>关键事件</strong><ul>' + events + '</ul></div>' : '') +
        (rels ? '<div><strong>涉及关系</strong><div class="cluster" style="margin-top:6px">' + rels + '</div></div>' : '') +
        (c.ending_hook ? '<p><strong>结尾钩子：</strong>' + escapeHtml(c.ending_hook) + '</p>' : '') +
        (c.plot_purpose ? '<p class="muted"><strong>定位：</strong>' + escapeHtml(c.plot_purpose) + '</p>' : '') +
        (c.target_chinese_chars ? '<p class="muted">目标字数：' + escapeHtml(String(c.target_chinese_chars)) + '</p>' : '') +
        '<div class="form-actions"><button type="button" class="btn btn-secondary" data-plan-page-edit="' + no + '">编辑章节计划</button></div>' +
        '</div>';
      return '<div class="card" style="margin-bottom:16px">' + head + body + '</div>';
    }).join("");
    box.innerHTML = arcHtml + cards;
    box.querySelectorAll("[data-plan-page-edit]").forEach(function (button) {
      button.addEventListener("click", function () { openPlanPageEditor(Number(button.dataset.planPageEdit), button); });
    });
  }
  function focusPlanEditButton(chapterNo) {
    setTimeout(function () {
      const target = document.querySelector('[data-plan-page-edit="' + chapterNo + '"]');
      if (target) target.focus();
    }, 0);
  }
  function openPlanPageEditor(chapterNo, trigger) {
    const box = document.querySelector('[data-plan-pane="chapters"]');
    const chapters = Array.isArray(planPageData && planPageData.plan && planPageData.plan.chapters)
      ? planPageData.plan.chapters : [];
    const chapter = chapters.find(function (item) { return Number(item.chapter_no) === chapterNo; });
    if (!box || !chapter) return;
    function value(id) { const el = document.getElementById(id); return el ? el.value.trim() : ""; }
    function listValue(id) { return value(id).split("\\n").map(function (item) { return item.trim(); }).filter(Boolean); }
    box.innerHTML =
      '<form id="plan-page-editor" class="card plan-page-editor" aria-busy="false">' +
      '<div class="card-header"><div><p class="eyebrow ornament">第 ' + chapterNo + ' 章</p><h2 id="plan-page-editor-title" tabindex="-1">编辑章节计划</h2></div></div>' +
      '<div class="card-body form-grid">' +
      '<div class="field"><label for="plan-page-title">章节标题</label><input id="plan-page-title" value="' + escapeHtml(chapter.title || "") + '"></div>' +
      '<div class="field"><label for="plan-page-opening">开场场景</label><textarea id="plan-page-opening" rows="3">' + escapeHtml(chapter.opening_scene || "") + '</textarea></div>' +
      '<div class="field"><label for="plan-page-events">核心事件（每行一项，共 2-7 项）</label><textarea id="plan-page-events" rows="5">' + escapeHtml((Array.isArray(chapter.key_events) ? chapter.key_events : []).join("\\n")) + '</textarea></div>' +
      '<div class="field"><label for="plan-page-relations">重点关系（每行一项，可留空）</label><textarea id="plan-page-relations" rows="4">' + escapeHtml((Array.isArray(chapter.relationships_in_play) ? chapter.relationships_in_play : []).filter(function (item) { return typeof item === "string"; }).join("\\n")) + '</textarea></div>' +
      '<div class="field"><label for="plan-page-hook">结尾承接</label><textarea id="plan-page-hook" rows="3">' + escapeHtml(chapter.ending_hook || "") + '</textarea></div>' +
      '<div class="field"><label for="plan-page-target">目标字数（2500-6000）</label><input id="plan-page-target" type="number" min="2500" max="6000" step="100" value="' + Number(chapter.target_chinese_chars || 4000) + '"></div>' +
      '<div class="field"><label for="plan-page-purpose">本章作用</label><textarea id="plan-page-purpose" rows="3">' + escapeHtml(chapter.plot_purpose || "") + '</textarea></div>' +
      '<div id="plan-page-error" role="status" aria-live="polite"></div>' +
      '<p class="muted">如果本章已有正文，保存后相关内容检查状态可能需要更新。</p>' +
      '<div class="form-actions"><button type="button" class="btn btn-ghost" id="plan-page-cancel">取消编辑</button><button type="submit" class="btn btn-primary" id="plan-page-save">保存章节计划</button></div>' +
      '</div></form>';
    const form = document.getElementById("plan-page-editor");
    let unregisterDirty = null;
    document.getElementById("plan-page-editor-title").focus();
    form.addEventListener("input", function () { form.dataset.dirty = "1"; });
    document.getElementById("plan-page-cancel").addEventListener("click", function () {
      if (unregisterDirty) unregisterDirty();
      renderPlanChapters(box, planPageData.plan || {}, planPageData.draft_chapters || [], planPageData.draft_verdicts || {});
      focusPlanEditButton(chapterNo);
    });
    async function savePlanPage() {
      const fields = {
        title: value("plan-page-title"), opening_scene: value("plan-page-opening"),
        key_events: listValue("plan-page-events"), relationships_in_play: listValue("plan-page-relations"),
        ending_hook: value("plan-page-hook"), target_chinese_chars: Number(value("plan-page-target")),
        plot_purpose: value("plan-page-purpose"),
      };
      const errorBox = document.getElementById("plan-page-error");
      if (!fields.title || !fields.opening_scene || !fields.ending_hook || !fields.plot_purpose || fields.key_events.length < 2 || fields.key_events.length > 7 || fields.target_chinese_chars < 2500 || fields.target_chinese_chars > 6000) {
        errorBox.innerHTML = '<div class="alert warn">请完整填写标题、开场、结尾承接和章节作用；核心事件需 2-7 项，目标字数需在 2500-6000 之间。</div>';
        return false;
      }
      setFormSubmitBusy(form, true, "正在保存");
      try {
        const submitted = captureEditSnapshot(form);
        const result = await putJson(wsUrl("/chapter-plan/" + chapterNo), { fields: fields });
        if (!acknowledgeEditSnapshot(submitted)) { setFormSubmitBusy(form, false); return false; }
        form.dataset.dirty = "0";
        if (unregisterDirty) unregisterDirty();
        const invalidated = Array.isArray(result.written_chapters_invalidated) ? result.written_chapters_invalidated : [];
        showToast(invalidated.length ? "章节计划已保存；相关内容检查状态需要更新" : "章节计划已保存", "info");
        await initPlan();
        focusPlanEditButton(chapterNo);
        return true;
      } catch (err) {
        errorBox.innerHTML = publicLoadError("章节计划没有保存成功", "输入内容仍保留，请检查后重试。", "");
        setFormSubmitBusy(form, false);
        return false;
      }
    }
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      await savePlanPage();
    });
    unregisterDirty = registerDirtyEditor("plan-page", {
      label: "章节计划",
      isDirty: function () { return form.isConnected && form.dataset.dirty === "1"; },
      save: savePlanPage,
      discard: function () { form.dataset.dirty = "0"; },
      focus: function () { form.focus(); },
    });
  }
  function renderOutlineMarkdown(box, md) {
    if (!box) return;
    if (!md || !md.trim()) {
      box.innerHTML = '<div class="empty-state"><h3>暂无可查看的大纲</h3><p class="muted">请回到创作工作台检查大纲准备状态。</p><a class="btn btn-secondary" href="' + wsHref('/workbench') + '">前往创作工作台</a></div>';
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
    const votes = Array.isArray(decisions && decisions.votes) ? decisions.votes.filter(function (item) { return item && typeof item === "object" && !Array.isArray(item); }) : [];
    if (!votes.length) {
      box.innerHTML = '<p class="muted">尚无创作讨论记录。</p>';
      return;
    }
    const head =
      '<div class="alert info" style="margin-bottom:16px">' +
      '<strong>主题：</strong>' + escapeHtml(typeof decisions.topic === "string" ? decisions.topic.slice(0, 240) : "未命名") +
      '　·　<strong>讨论片段：</strong>' + escapeHtml(String(safePublicCount(decisions.transcript_items))) +
      '</div>';
    const cards = votes.map(function (v) {
      const fors = (Array.isArray(v["for"]) ? v["for"].filter(function (item) { return typeof item === "string"; }) : []).join("；") || "—";
      const againsts = (Array.isArray(v.against) ? v.against.filter(function (item) { return typeof item === "string"; }) : []).join("；") || "—";
      const agentRows = Array.isArray(v.agent_votes) ? v.agent_votes.filter(function (item) { return item && typeof item === "object" && !Array.isArray(item); }) : [];
      const agents = agentRows.map(function (a, index) {
        return '<li><strong>参与角色 ' + (index + 1) + '</strong> · ' +
          escapeHtml(a.position || "—") + '：' + escapeHtml(a.reason || "—") + '</li>';
      }).join("");
      return (
        '<div class="card" style="margin-bottom:12px">' +
        '<div class="card-header"><h3>' + escapeHtml(v.question || "(无问题)") + '</h3></div>' +
        '<div class="card-body">' +
        '<p><strong>裁决：</strong>' + escapeHtml(v.result || "—") + '</p>' +
        '<p><strong>支持：</strong>' + escapeHtml(fors) + '</p>' +
        '<p><strong>反对：</strong>' + escapeHtml(againsts) + '</p>' +
        (agents ? '<details><summary class="muted">参与角色（' + agentRows.length + '）</summary><ul>' + agents + '</ul></details>' : '') +
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
      const entries = Array.isArray(data.entries) ? data.entries.filter(function (entry) {
        return entry && typeof entry === "object" && typeof entry.entry === "string" &&
          typeof entry.original_name === "string";
      }) : [];
      if (!entries.length) {
        box.innerHTML = emptyState("回收站是空的", "目前没有已删除的作品。", "");
        return;
      }
      const rows = entries.map(function (e) {
        return (
          '<article class="trash-card">' +
          '<div><p class="eyebrow ornament">已删除作品</p><h2>' + escapeHtml(e.original_name) + '</h2></div>' +
          '<dl class="trash-meta">' +
          '<div><dt>移入回收站</dt><dd>' + escapeHtml(publicDateLabel(e.deleted_at)) + '</dd></div>' +
          '<div><dt>当前状态</dt><dd>仍可恢复</dd></div>' +
          '</dl>' +
          '<div class="cluster trash-actions">' +
          '<button class="btn btn-secondary" data-trash-restore="' + escapeHtml(e.entry) +
          '" data-trash-name="' + escapeHtml(e.original_name) + '">恢复作品</button>' +
          '<button class="btn btn-danger btn-sm" data-trash-purge="' + escapeHtml(e.entry) +
          '" data-trash-name="' + escapeHtml(e.original_name) + '">永久删除</button>' +
          '</div></article>'
        );
      }).join("");
      box.innerHTML = rows;
    } catch (err) {
      box.innerHTML = publicLoadError(
        "回收站没有读取成功",
        "回收站中的内容仍然保留，没有执行恢复或删除。请重新加载后再试。",
        '<button type="button" class="btn btn-secondary" data-cta-action="reload">重新加载</button>'
      );
    }
  }
  document.addEventListener("click", async function (ev) {
    const r = ev.target.closest("[data-trash-restore]");
    if (r) {
      ev.preventDefault();
      const entry = r.getAttribute("data-trash-restore");
      showRestoreModal(entry, r.getAttribute("data-trash-name") || "作品");
      return;
    }
    const p = ev.target.closest("[data-trash-purge]");
    if (p) {
      ev.preventDefault();
      showPurgeModal(p.getAttribute("data-trash-purge"), p.getAttribute("data-trash-name") || "作品");
    }
  });
  function showRestoreModal(entry, originalName) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="restore-title">' +
      '<div class="modal-header" id="restore-title">恢复作品</div>' +
      '<div class="modal-body"><p>将把《' + escapeHtml(originalName) + '》恢复到作品列表。</p>' +
      '<p class="muted">作品内容会保持原样，其他作品不会受到影响。</p><div id="modal-restore-error"></div></div>' +
      '<div class="modal-footer"><button type="button" class="btn btn-ghost" data-modal-close>取消</button>' +
      '<button type="button" class="btn btn-secondary" id="modal-restore-btn">确认恢复</button></div></div>';
    const btn = backdrop.querySelector("#modal-restore-btn");
    const err = backdrop.querySelector("#modal-restore-error");
    const close = mountModal(backdrop, { initialFocus: btn });
    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop || ev.target.hasAttribute("data-modal-close")) close();
    });
    btn.addEventListener("click", async function () {
      setControlBusy(btn, true, "正在恢复");
      try {
        const data = await postJson("/api/trash/" + encodeURIComponent(entry) + "/restore", {});
        close();
        showToast("已恢复作品：《" + data.restored_to + "》", "info");
        await reloadTrashList();
      } catch (error) {
        err.innerHTML = publicLoadError(
          "恢复没有完成", "作品仍在回收站中。请检查是否已有同名作品，再重新尝试。", ""
        );
        setControlBusy(btn, false);
      }
    });
  }
  function showPurgeModal(entry, originalName) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="purge-title">' +
      '<div class="modal-header" id="purge-title">永久删除作品</div>' +
      '<div class="modal-body">' +
      '<p>将永久删除《' + escapeHtml(originalName) + '》及其中保存的本地内容，<strong>完成后无法恢复</strong>。</p>' +
      '<p class="muted">只会删除这一部作品，其他作品不会受到影响。</p>' +
      '<p>请输入作品名称 <strong>' + escapeHtml(originalName) + '</strong> 以继续。</p>' +
      '<div class="field"><label for="modal-purge-input">确认名称</label>' +
      '<input type="text" id="modal-purge-input" autocomplete="off" aria-describedby="modal-purge-error">' +
      '</div>' +
      '<div id="modal-purge-error" role="status" aria-live="polite"></div>' +
      '</div>' +
      '<div class="modal-footer">' +
      '<button type="button" class="btn btn-ghost" data-modal-close>取消</button>' +
      '<button type="button" class="btn btn-danger" id="modal-purge-btn" disabled>确认永久删除</button>' +
      '</div></div>';
    const input = backdrop.querySelector("#modal-purge-input");
    const btn = backdrop.querySelector("#modal-purge-btn");
    const cancel = backdrop.querySelector("[data-modal-close]");
    const err = backdrop.querySelector("#modal-purge-error");
    let committed = false;
    const close = mountModal(backdrop, { initialFocus: input, canClose: function () { return !committed; } });
    input.addEventListener("input", function () {
      btn.disabled = input.value !== originalName;
    });
    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop || ev.target.hasAttribute("data-modal-close")) close();
    });
    btn.addEventListener("click", async function () {
      committed = true;
      input.disabled = true;
      cancel.disabled = true;
      setControlBusy(btn, true, "正在删除");
      err.innerHTML = '<div class="alert info">正在永久删除；完成前请不要关闭页面。</div>';
      try {
        await postJson("/api/trash/" + encodeURIComponent(entry) + "/purge", { confirm: entry });
        committed = false;
        close();
        showToast("已永久删除作品：《" + originalName + "》", "info");
        await reloadTrashList();
      } catch (e) {
        committed = false;
        input.disabled = false;
        cancel.disabled = false;
        err.innerHTML = publicLoadError(
          "永久删除没有完成", "作品内容仍保留在回收站中。请保持页面打开并重新尝试。", ""
        );
        setControlBusy(btn, false);
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
    bindCtaActions();
    // iter068 (Cluster A): an existing book (has_start_point) must rebuild its
    // continuation base — NOT run greenfield onboarding. The stage ① job, and
    // the require_start_point gate on plan-chapters / write-book, all follow
    // lastWorkbenchStatus.has_start_point so the workbench never silently
    // bypasses the start-point consistency gate for a real continuation.
    const isGreenfield = function () {
      return !!(lastWorkbenchStatus && lastWorkbenchStatus.creation_mode === "greenfield");
    };
    bindWorkbenchStage("prepare-form", "prepare-submit", "prepare-status",
      function () { return isGreenfield() ? "prepare-greenfield" : "rebuild-for-start"; },
      function () {
        const limit = isGreenfield() ? NOVEL_STAGE_LIMITS["prepare-greenfield"] : NOVEL_STAGE_LIMITS["rebuild-for-start"];
        // rebuild = 补齐底座（reextract 默认 false，只补缺口）；greenfield = 强制重提。
        return Object.assign(isGreenfield() ? { force: true } : { window: 10 }, limit);
      });
    bindWorkbenchStage("outline-form", "outline-submit", "outline-status", "debate", function () {
      return Object.assign({}, NOVEL_STAGE_LIMITS.debate);
    });
    bindWorkbenchStage("plan-chapters-form", "plan-chapters-submit", "plan-chapters-status", "plan-chapters", function (form) {
      // require_start_point follows has_start_point: an existing book MUST enforce
      // the gate (else plan drifts off the real start); a greenfield premise has
      // no prior start point so it stays false.
      return Object.assign({ target_chapters: Number(form.elements.target_chapters.value || 5) }, NOVEL_STAGE_LIMITS["plan-chapters"]);
    });
    bindWorkbenchStage("write-book-form", "write-book-submit", "write-book-status", "write-book", function (form) {
      return {
        chapters: Number(form.elements.chapters.value || 1),
        tier: form.elements.tier ? form.elements.tier.value || "mid" : "mid",
        budget_cny: form.elements.budget_cny ? Number(form.elements.budget_cny.value || NOVEL_STAGE_LIMITS["write-book"].budget_cny) : NOVEL_STAGE_LIMITS["write-book"].budget_cny,
        timeout_minutes: form.elements.timeout_minutes ? Number(form.elements.timeout_minutes.value || NOVEL_STAGE_LIMITS["write-book"].timeout_minutes) : NOVEL_STAGE_LIMITS["write-book"].timeout_minutes,
        max_model_requests: form.elements.max_model_requests ? Number(form.elements.max_model_requests.value || NOVEL_STAGE_LIMITS["write-book"].max_model_requests) : NOVEL_STAGE_LIMITS["write-book"].max_model_requests,
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
  let workbenchBulkSaving = false;
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
        kbArea.placeholder = "知识库尚未生成；请检查当前步骤后重试。";
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
        const submitted = captureEditSnapshot(kbArea);
        await putJson(wsUrl("/kb"), { content: kbArea.value });
        if (!acknowledgeEditSnapshot(submitted)) return;
        showToast("知识库已保存；下游大纲 / 细纲将提示重新生成", "info");
        if (!workbenchBulkSaving) await refreshWorkbench();
      } catch (err) {
        showToast("保存失败：" + errTitle(err), "error");
      } finally {
        kbSave.disabled = false;
      }
    });
    registerDirtyEditor("workbench-kb", {
      label: "作品知识库",
      isDirty: function () { return kbArea.isConnected && kbArea.dataset.dirty === "1"; },
      save: function () { return clickAndAwaitClean(kbSave, function () { return kbArea.dataset.dirty === "1"; }); },
      discard: function () { delete kbArea.dataset.dirty; },
      focus: function () { kbArea.focus(); },
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
        const submitted = captureEditSnapshot(els[EXPANSION_FIELDS[0].key], EXPANSION_FIELDS.map(function (f) { return els[f.key]; }));
        await putJson(wsUrl("/premise-expansion"), { fields: fields });
        if (!acknowledgeEditSnapshot(submitted)) return;
        showToast("扩写稿已保存；需重新生成作品知识与角色设定才会生效", "info");
        if (!workbenchBulkSaving) await refreshWorkbench();
      } catch (err) {
        showToast("保存失败：" + errTitle(err), "error");
      } finally {
        save.disabled = false;
      }
    });
    regen.addEventListener("click", async function () {
      if (!await confirmPaidAction({
        title: "确认重新扩写",
        action: "将重新生成立意扩写稿，并覆盖当前扩写稿（包括手工修改）。",
        scope: paidLimitScope("扩写稿 1 份", NOVEL_STAGE_LIMITS["expand-premise"]),
        preservation: "作品其它内容会保留；开始后可在任务记录中查看进度或请求取消。",
      })) return;
      setControlBusy(regen, true, "处理中");
      if (box) box.innerHTML = '<div class="alert info">正在重新扩写…</div>';
      try {
        const data = await postModelRun(wsUrl("/run"), {
          step: "expand-premise",
          params: Object.assign({ force: true }, NOVEL_STAGE_LIMITS["expand-premise"]),
        });
        setWorkbenchMutationLock(true);
        renderWorkbenchHydration("running", { job_id: data.job_id, step: "expand-premise", status: "pending" });
        await pollJob(data.job_id, box, regen, async function () {
          for (const f of EXPANSION_FIELDS) delete els[f.key].dataset.dirty;
          await loadExpansionPanel();
          await refreshWorkbench();
        });
      } catch (err) {
        if (box) box.innerHTML = renderErrorCard(err);
        setControlBusy(regen, false);
      }
    });
    registerDirtyEditor("workbench-expansion", {
      label: "立意扩写稿",
      isDirty: function () { return EXPANSION_FIELDS.some(function (f) { return els[f.key].isConnected && els[f.key].dataset.dirty === "1"; }); },
      save: function () { return clickAndAwaitClean(save, function () { return EXPANSION_FIELDS.some(function (f) { return els[f.key].dataset.dirty === "1"; }); }); },
      discard: function () { EXPANSION_FIELDS.forEach(function (f) { delete els[f.key].dataset.dirty; }); },
      focus: function () { els[EXPANSION_FIELDS[0].key].focus(); },
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
    let continuation = true;
    try { continuation = (await fetchJson(wsUrl("/workbench"))).creation_mode !== "greenfield"; } catch (err) {}
    const body = document.getElementById("style-card-body");
    if (continuation) {
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
        const submitted = captureEditSnapshot(els[STYLE_FIELDS[0].key], STYLE_FIELDS.map(function (f) { return els[f.key]; }));
        await putJson(wsUrl("/writer-style"), { fields: fields });
        if (!acknowledgeEditSnapshot(submitted)) return;
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
      if (!await confirmPaidAction({
        title: "确认提取写作风格",
        action: "将从你提供的样本中提取写作风格。",
        scope: paidLimitScope("风格卡 1 份", { max_model_requests: 2, budget_cny: 2, timeout_minutes: 15 }),
        preservation: "样本文本不会覆盖作品正文；开始后可在任务记录中查看进度。",
      })) return;
      setControlBusy(extractBtn, true, "处理中");
      if (box) box.innerHTML = '<div class="alert info">正在提取风格特征…</div>';
      try {
        const resp = await fetch(wsUrl("/writer-style/extract"), {
          method: "POST",
          headers: { "X-Model-Action-Intent": "extract-style-v1" },
          body: fd,
        });
        const data = await resp.json().catch(function () { return {}; });
        if (!resp.ok) throw new Error(data.error || ("HTTP " + resp.status));
        setWorkbenchMutationLock(true);
        renderWorkbenchHydration("running", { job_id: data.job_id, step: "extract-style", status: "pending" });
        await pollJob(data.job_id, box, extractBtn, async function () {
          for (const f of STYLE_FIELDS) delete els[f.key].dataset.dirty;
          await loadStyleCardPanel();
          showToast("已提取风格卡；可微调后保存", "info");
        });
      } catch (err) {
        if (box) box.innerHTML = renderErrorCard(err);
        setControlBusy(extractBtn, false);
      }
    });
    registerDirtyEditor("workbench-style", {
      label: "作家风格卡",
      isDirty: function () { return STYLE_FIELDS.some(function (f) { return els[f.key].isConnected && els[f.key].dataset.dirty === "1"; }); },
      save: function () { return clickAndAwaitClean(save, function () { return STYLE_FIELDS.some(function (f) { return els[f.key].dataset.dirty === "1"; }); }); },
      discard: function () { STYLE_FIELDS.forEach(function (f) { delete els[f.key].dataset.dirty; }); },
      focus: function () { els[STYLE_FIELDS[0].key].focus(); },
    });
  }
  async function renderEntityPanel() {
    const box = document.getElementById("entity-panel");
    if (!box) return;
    Array.from(dirtyEditorRegistry.keys()).forEach(function (key) {
      if (key.indexOf("workbench-entity-") === 0 || key.indexOf("workbench-rel-") === 0) dirtyEditorRegistry.delete(key);
    });
    let graph;
    try {
      graph = await fetchJson(wsUrl("/entity-graph"));
    } catch (err) {
      box.innerHTML = '<p class="muted">实体图谱尚未生成。</p>';
      return;
    }
    const entities = (Array.isArray(graph.entities) ? graph.entities : []).filter(function (e) {
      return isPlainObject(e) && typeof e.id === "string" && e.id;
    });
    const rels = (Array.isArray(graph.relationships) ? graph.relationships : []).filter(isPlainObject);
    const entityNames = {};
    entities.forEach(function (e) { entityNames[e.id] = typeof e.name === "string" && e.name ? e.name : "未命名人物"; });
    let html = '<div class="field"><label>实体（名称 / 核心事实 / 描写可编辑）</label></div>';
    entities.forEach(function (e, i) {
      const facts = (Array.isArray(e.key_facts) ? e.key_facts : []).filter(function (fact) { return typeof fact === "string"; }).join("\\n");
      html += '<div class="card" style="margin-bottom:8px"><div class="card-body">' +
        '<div class="field"><label for="ent-name-' + i + '">名称</label>' +
        '<input type="text" id="ent-name-' + i + '" value="' + escapeHtml(typeof e.name === "string" ? e.name : "") + '"></div>' +
        '<div class="field"><label for="ent-facts-' + i + '">核心事实（每行一条）</label>' +
        '<textarea id="ent-facts-' + i + '" rows="3">' + escapeHtml(facts) + '</textarea></div>' +
        '<div class="field"><label for="ent-desc-' + i + '">描写</label>' +
        '<textarea id="ent-desc-' + i + '" rows="2">' + escapeHtml(typeof e.description === "string" ? e.description : "") + '</textarea></div>' +
        '<div class="form-actions" style="justify-content:flex-end">' +
        '<button type="button" class="btn btn-ghost btn-sm" data-entity-save="' + i + '" data-entity-id="' + escapeHtml(String(e.id)) + '">保存实体</button>' +
        '</div></div></div>';
    });
    const activeRels = [];
    rels.forEach(function (r, idx) {
      const active = (Array.isArray(r.timeline) ? r.timeline : []).find(function (t) { return isPlainObject(t) && t.active === true; });
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
          '<input type="text" id="rel-state-' + item.idx + '" value="' + escapeHtml(typeof item.active.state === "string" ? item.active.state : "") + '" style="flex:1">' +
          '<button type="button" class="btn btn-ghost btn-sm" data-rel-save="' + item.idx + '"' +
          ' data-src-id="' + escapeHtml(String(r.src_id || "")) + '"' +
          ' data-dst-id="' + escapeHtml(String(r.dst_id || "")) + '">保存</button>' +
          '</div></div>';
      });
    }
    box.innerHTML = html;
    box.querySelectorAll("[data-entity-save]").forEach(function (btn) {
      const i = btn.dataset.entitySave;
      const inputs = [document.getElementById("ent-name-" + i), document.getElementById("ent-facts-" + i), document.getElementById("ent-desc-" + i)];
      inputs.forEach(function (input) { input.addEventListener("input", function () { input.dataset.dirty = "1"; }); });
      btn.addEventListener("click", async function () {
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
          const submitted = captureEditSnapshot(inputs[0], inputs);
          await putJson(wsUrl("/entity/" + encodeURIComponent(btn.dataset.entityId)), { fields: fields });
          if (!acknowledgeEditSnapshot(submitted)) return;
          showToast("实体已保存：" + fields.name, "info");
        } catch (err) {
          showToast("保存失败：" + errTitle(err), "error");
        } finally {
          btn.disabled = false;
        }
      });
      registerDirtyEditor("workbench-entity-" + btn.dataset.entityId, {
        label: "实体“" + (inputs[0].value || "未命名") + "”",
        isDirty: function () { return inputs.some(function (input) { return input.isConnected && input.dataset.dirty === "1"; }); },
        save: function () { return clickAndAwaitClean(btn, function () { return inputs.some(function (input) { return input.dataset.dirty === "1"; }); }); },
        discard: function () { inputs.forEach(function (input) { delete input.dataset.dirty; }); },
        focus: function () { inputs[0].focus(); },
      });
    });
    box.querySelectorAll("[data-rel-save]").forEach(function (btn) {
      const input = document.getElementById("rel-state-" + btn.dataset.relSave);
      input.addEventListener("input", function () { input.dataset.dirty = "1"; });
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
          const submitted = captureEditSnapshot(input);
          await putJson(wsUrl("/relationship/" + idx), {
            state: state,
            src_id: btn.dataset.srcId || "",
            dst_id: btn.dataset.dstId || "",
          });
          if (!acknowledgeEditSnapshot(submitted)) return;
          showToast("关系状态已保存", "info");
        } catch (err) {
          showToast("保存失败：" + errTitle(err), "error");
          if (err.payload && err.payload.stale_index) {
            showToast("关系数据已变化；当前输入已保留，请核对后重试", "warn");
          }
        } finally {
          btn.disabled = false;
        }
      });
      registerDirtyEditor("workbench-rel-" + btn.dataset.relSave, {
        label: "人物关系",
        isDirty: function () { return input.isConnected && input.dataset.dirty === "1"; },
        save: function () { return clickAndAwaitClean(btn, function () { return input.dataset.dirty === "1"; }); },
        discard: function () { delete input.dataset.dirty; },
        focus: function () { input.focus(); },
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
      if (!lastWorkbenchStatus) {
        if (box) box.innerHTML = publicLoadError("状态尚未读取完成", "所有操作保持锁定，请重新读取状态后再试。", "");
        return;
      }
      // iter068 (Cluster A): step may be a function so the same form can dispatch
      // a different job by current state — stage ① runs rebuild-for-start for an
      // existing book (has_start_point) but prepare-greenfield for a greenfield
      // premise. Resolved here at submit time, after refreshWorkbench populated
      // lastWorkbenchStatus.
      const stepName = typeof step === "function" ? step() : step;
      const params = paramsFn ? paramsFn(form) : {};
      if (stepName === "write-book") {
        setFormSubmitBusy(form, true, "正在检查");
        if (box) box.innerHTML = '<div class="alert info">正在检查是否可以继续…</div>';
        let readiness;
        try {
          readiness = await fetchJson(wsUrl("/readiness?chapters=" + encodeURIComponent(params.chapters || 1) + "&resume_from=1&replan_every=0"));
        } catch (err) {
          if (box) box.innerHTML = publicLoadError("续写入口检查失败", "没有开始生成，请稍后重试检查。", "");
          setFormSubmitBusy(form, false);
          return;
        }
        setFormSubmitBusy(form, false);
        if (!readiness || (readiness.status !== "ready" && readiness.status !== "warn")) {
          const primary = readiness && readiness.primary_blocker;
          const reason = primary && typeof primary.kind === "string"
            ? readinessReasonText(primary.kind)
            : "当前还不能开始正文，请先完成页面提示的准备步骤。";
          if (box) box.innerHTML = publicLoadError("需要先完成准备", reason, "");
          return;
        }
      }
      if (!await confirmPaidAction({
        title: "确认" + stepLabel(stepName),
        action: "将开始“" + stepLabel(stepName) + "”。",
        scope: paidLimitScope("当前阶段", params),
        preservation: "已有作品内容会保留；开始后可在任务记录中查看进度或请求取消。",
      })) return;
      setFormSubmitBusy(form, true, "处理中");
      if (box) box.innerHTML = '<div class="alert info">正在启动“' + escapeHtml(stepLabel(stepName)) + "”…</div>";
      try {
        const data = await postModelRun(wsUrl("/run"), { step: stepName, params: params });
        setWorkbenchMutationLock(true);
        renderWorkbenchHydration("running", { job_id: data.job_id, step: stepName, status: "pending" });
        await pollJob(data.job_id, box, submit, async () => {
          await refreshWorkbench();
          // iter 050d (M-2): stage ① rewrites KB/entity_graph — reload the
          // settings panel if it's open so indices don't go stale. Both the
          // greenfield and rebuild-for-start variants touch those artifacts.
          if ((stepName === "prepare-greenfield" || stepName === "rebuild-for-start") && settingsPanelInvalidate) settingsPanelInvalidate();
        });
      } catch (err) {
        if (box) box.innerHTML = renderErrorCard(err);
      } finally {
        setFormSubmitBusy(form, false);
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
        const submitted = captureEditSnapshot(area);
        await putJson(wsUrl("/outline"), { outline: area.value });
        if (!acknowledgeEditSnapshot(submitted)) return;
        showToast("大纲已保存", "info");
        if (!workbenchBulkSaving) await refreshWorkbench();
      } catch (err) {
        showToast("保存失败：" + errTitle(err), "error");
      } finally {
        btn.disabled = false;
      }
    });
    registerDirtyEditor("workbench-outline", {
      label: "故事大纲",
      isDirty: function () { return area.isConnected && area.dataset.dirty === "1"; },
      save: function () { return clickAndAwaitClean(btn, function () { return area.dataset.dirty === "1"; }); },
      discard: function () { delete area.dataset.dirty; },
      focus: function () { area.focus(); },
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
      { key: "prepare", label: "① 准备设定", target: "stage-prepare-card", done: !!st.has_kb, locked: false },
      { key: "outline", label: "② 生成大纲", target: "stage-outline-card", done: !!st.has_outline, locked: !st.has_kb },
      { key: "plan", label: "③ 生成细纲", target: "stage-plan-card", done: !!st.has_plan, locked: !st.has_outline },
      { key: "write", label: "④ 撰写正文", target: "stage-write-card", done: st.stage === "done", locked: !st.has_plan },
    ];
    steps.forEach(function (s) {
      const card = document.getElementById(s.target);
      const header = card && card.querySelector(".card-header");
      if (!card || !header) return;
      const current = st.stage === s.key;
      const running = Array.isArray(st.running_stages) && st.running_stages.indexOf(s.key) >= 0;
      const needsUpdate = s.key === "prepare" && st.expansion_stale === true;
      const state = running ? "正在处理" : needsUpdate ? "需要更新" : s.done ? "已完成" : s.locked ? "未开始" : "可以开始";
      card.dataset.stageState = running ? "running" : needsUpdate ? "stale" : s.done ? "completed" : current ? "current" : s.locked ? "not-started" : "ready";
      let marker = header.querySelector(".stage-state-label");
      if (!marker) {
        marker = document.createElement("span");
        marker.className = "badge no-dot stage-state-label";
        header.appendChild(marker);
      }
      marker.textContent = state;
    });
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
  let recoveredWorkbenchJobId = "";
  function setWorkbenchMutationLock(locked) {
    document.querySelectorAll('[data-workbench-mutation],#expansion-regen,#style-extract-btn,[data-style-activate],[data-entity-save],[data-rel-save],[data-plan-edit]').forEach(function (control) {
      control.disabled = !!locked;
    });
  }
  function renderWorkbenchHydration(kind, job) {
    const note = document.querySelector(".workbench-running-note");
    if (!note) return;
    if (kind === "loading") {
      note.innerHTML = '<span class="muted">正在读取作品与任务状态…</span>';
    } else if (kind === "error") {
      note.innerHTML = '<div class="alert error">状态读取失败，所有修改操作已锁定。<button type="button" class="btn btn-secondary btn-sm" id="workbench-retry">重新读取</button></div>';
      const retry = document.getElementById("workbench-retry");
      if (retry) retry.addEventListener("click", refreshWorkbench);
    } else if (kind === "running" && job) {
      note.innerHTML = '<div class="alert info"><strong>' + escapeHtml(stepLabel(job.step)) + '正在处理</strong>。冲突操作已锁定。 ' +
        '<span id="workbench-active-progress">' + escapeHtml(statusLabel(job.status || "running")) + '</span> ' +
        '<a class="btn btn-secondary btn-sm" href="' + wsHref('/jobs') + '">查看任务</a> ' +
        '<button type="button" class="btn btn-ghost btn-sm" id="workbench-cancel-active">请求取消</button></div>';
      const cancel = document.getElementById("workbench-cancel-active");
      if (cancel) cancel.addEventListener("click", async function () {
        cancel.disabled = true;
        try { await postJson(wsUrl("/job/" + job.job_id + "/cancel"), {}); showToast("已请求取消任务", "info"); }
        catch (err) { showToast(errTitle(err), "error"); cancel.disabled = false; }
      });
    } else if (kind === "reconcile") {
      note.innerHTML = '<div class="alert warn">任务状态无法确认，已停止刷新且不会自动重提。请前往任务记录核对后再继续。 ' +
        '<a class="btn btn-secondary btn-sm" href="' + wsHref('/jobs') + '">查看任务</a></div>';
    } else {
      note.textContent = "任务开始后可以离开此页，处理仍会继续；随时从“任务记录”返回查看。";
    }
  }
  async function watchRecoveredWorkbenchJob(job) {
    if (!job || !job.job_id || recoveredWorkbenchJobId === job.job_id) return;
    recoveredWorkbenchJobId = job.job_id;
    while (recoveredWorkbenchJobId === job.job_id) {
      await new Promise(function (resolve) { setTimeout(resolve, 1200); });
      let current;
      try { current = await fetchJson(wsUrl("/job/" + job.job_id)); }
      catch (err) {
        renderWorkbenchHydration("error");
        recoveredWorkbenchJobId = "";
        return;
      }
      if (!current || !["pending", "running", "succeeded", "failed", "blocked", "aborted", "budget_exceeded", "lost", "submission_unknown", "request_not_sent", "provider_rejected"].includes(current.status)) {
        renderWorkbenchHydration("error");
        recoveredWorkbenchJobId = "";
        return;
      }
      if (current.status === "lost" || current.status === "submission_unknown") {
        setWorkbenchMutationLock(true);
        renderWorkbenchHydration("reconcile");
        recoveredWorkbenchJobId = "";
        return;
      }
      const progress = document.getElementById("workbench-active-progress");
      if (progress) {
        const pct = Number.isFinite(Number(current.progress)) ? Math.round(Number(current.progress) * 100) + "%" : "";
        progress.textContent = statusLabel(current.status) + (pct ? " · " + pct : "");
      }
      if (current.status !== "pending" && current.status !== "running") {
        recoveredWorkbenchJobId = "";
        await refreshWorkbench();
        return;
      }
    }
  }
  async function refreshWorkbench() {
    setWorkbenchMutationLock(true);
    renderWorkbenchHydration("loading");
    let st;
    let activeJobs = [];
    let recentJob = null;
    try {
      const results = await Promise.all([
        fetchJson(wsUrl("/workbench")),
        fetchJson(wsUrl("/jobs/active")),
        fetchJson(wsUrl("/jobs/recent?n=1")),
      ]);
      st = results[0];
      const activeData = results[1];
      recentJob = results[2] && Array.isArray(results[2].jobs) ? results[2].jobs[0] || null : null;
      activeJobs = (Array.isArray(activeData.jobs) ? activeData.jobs : []).filter(function (job) { return job && (job.status === "pending" || job.status === "running"); });
      const stageByStep = {
        "prepare-greenfield": "prepare", "prepare-import": "prepare", "rebuild-for-start": "prepare",
        debate: "outline", "plan-chapters": "plan", "write-book": "write", "review-chapter": "write",
      };
      st.running_stages = activeJobs.map(function (job) {
        return stageByStep[String(job && job.step || "")] || "";
      }).filter(Boolean);
    } catch (err) {
      lastWorkbenchStatus = null;
      renderWorkbenchHydration("error");
      return;
    }
    const activeJob = activeJobs[0] || null;
    const reconcileJob = !activeJob && recentJob && (
      recentJob.status === "submission_unknown" ||
      (recentJob.status === "lost" && recentJob.reconciliation_reason === "worker_restart")
    );
    const pill = document.getElementById("workbench-stage-pill");
    if (pill) {
      const labels = { prepare: "① 准备设定", outline: "② 生成大纲", plan: "③ 生成细纲", write: "④ 撰写正文", done: "✓ 已出稿" };
      // iter062: surface a single "next step" primary CTA next to the badge.
      const next = !st.has_kb ? { l: st.creation_mode === "greenfield" ? "生成设定" : (st.has_start_point ? "重建续写底座" : "选择续写起点"), t: st.requires_start_point && !st.has_start_point ? "" : "stage-prepare-card" }
        : !st.has_outline ? { l: "生成大纲", t: "stage-outline-card" }
        : !st.has_plan ? { l: "生成细纲", t: "stage-plan-card" }
        : st.write_state === "retry_required" ? { l: "处理失败稿", t: "stage-write-card" }
        : st.stage !== "done" ? { l: "开始续写", t: "stage-write-card" }
        : null;
      const cta = next && next.t
        ? ' <a class="btn btn-primary btn-sm" href="#' + next.t + '">下一步：' + escapeHtml(next.l) + "</a>"
        : next ? ' <a class="btn btn-primary btn-sm" href="' + wsHref('/continue') + '">下一步：' + escapeHtml(next.l) + "</a>"
        : ' <a class="btn btn-secondary btn-sm" href="' + wsHref("/chapters") + '">查看章节</a>';
      pill.innerHTML = '<span class="badge">当前：' + escapeHtml(labels[st.stage] || "状态待确认") + "</span>" + cta;
    }
    renderStepbar(st);
    // iter 051a: KB older than the (edited) expansion → tell the user to
    // re-run stage ① instead of silently writing on stale settings.
    const expansionStaleHint = document.getElementById("expansion-stale-hint");
    if (expansionStaleHint) {
      expansionStaleHint.innerHTML = st.expansion_stale
        ? '<div class="alert warn">扩写稿已更新：请重新生成作品知识与角色设定，后续大纲与细纲会提示重建。</div>'
        : "";
    }
    // Gate each stage on its prerequisite artifact (mtime-validated server-side).
    setWorkbenchMutationLock(false);
    setStageEnabled("prepare-submit", !(st.requires_start_point && !st.has_start_point));
    setStageEnabled("settings-toggle", !!st.has_kb);
    setStageEnabled("outline-submit", !!st.has_kb);
    setStageEnabled("outline-save", !!st.has_outline);
    setStageEnabled("plan-chapters-submit", !!st.has_outline);
    const writeSubmit = document.getElementById("write-book-submit");
    const recoverySubmit = document.getElementById("write-recovery-submit");
    const openChapter = document.getElementById("write-book-open-chapter");
    const retryRequired = st.write_state === "retry_required" && Number(st.retry_chapter) > 0;
    setStageEnabled("write-book-submit", !!st.has_plan && st.stage !== "done" && !retryRequired);
    setStageEnabled("write-recovery-submit", retryRequired);
    if (writeSubmit) writeSubmit.hidden = st.stage === "done" || retryRequired;
    if (recoverySubmit) {
      recoverySubmit.hidden = !retryRequired;
      if (retryRequired) recoverySubmit.setAttribute("data-write-recovery-chapter", String(st.retry_chapter));
      else recoverySubmit.removeAttribute("data-write-recovery-chapter");
    }
    if (openChapter) openChapter.hidden = st.stage !== "done";
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
    if (st.creation_mode !== "greenfield") {
      if (prepareSubmit) prepareSubmit.textContent = "重建续写底座";
      if (prepareSubtitle) prepareSubtitle.textContent = st.has_start_point ? "已有续写起点：补充起点附近设定并重建续写底座" : "请先选择续写起点，再重建续写底座";
      if (prepareHint) prepareHint.textContent = st.has_start_point ? "将对起点前最近章节补齐提取，并据此重建续写底座（补齐底座，不强制全量重提）。" : "导入作品需要明确从哪里开始续写；系统不会把它当作原创新书。";
    } else {
      if (prepareSubmit) prepareSubmit.textContent = "生成设定";
      if (prepareSubtitle) prepareSubtitle.textContent = "从开书的一句话立意提取知识库与实体设定";
      if (prepareHint) prepareHint.textContent = "开书时填写的立意已保存；点右侧生成作品知识与角色设定。";
    }
    if (st.has_outline) {
      setWorkbenchMutationLock(true);
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
        renderWorkbenchHydration("error");
        return;
      }
      const area = document.getElementById("outline-md");
      if (area && !area.dataset.dirty && document.activeElement !== area) {
        if (typeof plan.outline_md === "string") area.value = plan.outline_md;
      }
      renderPlanPreview(plan && plan.plan, st);
      planPreviewLoaded = true;
    }
    if (reconcileJob) {
      setWorkbenchMutationLock(true);
      renderWorkbenchHydration("reconcile");
    } else if (activeJob) {
      setWorkbenchMutationLock(true);
      renderWorkbenchHydration("running", activeJob);
      watchRecoveredWorkbenchJob(activeJob);
    } else {
      recoveredWorkbenchJobId = "";
      setWorkbenchMutationLock(false);
      setStageEnabled("prepare-submit", !(st.requires_start_point && !st.has_start_point));
      setStageEnabled("settings-toggle", !!st.has_kb);
      setStageEnabled("outline-submit", !!st.has_kb);
      setStageEnabled("outline-save", !!st.has_outline);
      setStageEnabled("plan-chapters-submit", !!st.has_outline);
      setStageEnabled("write-book-submit", !!st.has_plan && st.stage !== "done" && !retryRequired);
      setStageEnabled("write-recovery-submit", retryRequired);
      renderWorkbenchHydration("ready");
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
    function markListDirty() {
      container.dispatchEvent(new Event("input", { bubbles: true }));
    }
    function rebindDel() {
      container.querySelectorAll("[data-row-del]").forEach(function (btn) {
        btn.onclick = function () {
          btn.parentElement.remove();
          markListDirty();
        };
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
      markListDirty();
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
    const editorRoot = box.querySelector(".plan-edit-form");
    let unregisterDirty = null;
    editorRoot.addEventListener("input", function () { editorRoot.dataset.dirty = "1"; });
    bindPlanEditorList(document.getElementById("plan-edit-events"), "事件描述", document.getElementById("plan-edit-events-add"), 7);
    bindPlanEditorList(document.getElementById("plan-edit-rels"), "如：路明非 ↔ 陈雯雯", document.getElementById("plan-edit-rels-add"), 20);
    document.getElementById("plan-edit-cancel").addEventListener("click", function () {
      if (unregisterDirty) unregisterDirty();
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
        const submitted = captureEditSnapshot(editorRoot);
        const res = await putJson(wsUrl("/chapter-plan/" + chapterNo), { fields: fields });
        if (!acknowledgeEditSnapshot(submitted)) return;
        // Retire the old editor synchronously before async refresh detaches it.
        editorRoot.innerHTML = '<p class="muted" role="status">已保存，正在刷新章节计划…</p>';
        if (unregisterDirty) unregisterDirty();
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
    const savePlanButton = document.getElementById("plan-edit-save");
    unregisterDirty = registerDirtyEditor("workbench-inline-plan", {
      label: "第" + num + "章细纲",
      isDirty: function () { return editorRoot.isConnected && editorRoot.dataset.dirty === "1"; },
      save: function () { return clickAndAwaitClean(savePlanButton, function () { return editorRoot.dataset.dirty === "1"; }); },
      discard: function () { delete editorRoot.dataset.dirty; },
      focus: function () { editorRoot.querySelector("input,textarea").focus(); },
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
      const target = Number(form.elements.target_chapters.value || 5);
      if (!await confirmPaidAction({
        title: "确认重新生成计划",
        action: "将生成并覆盖未来章节计划。",
        scope: paidLimitScope("计划 " + target + " 章", NOVEL_STAGE_LIMITS["plan-chapters"]),
        preservation: "已有正文会保留；新计划生成后请复核再继续写作。",
      })) return;
      setControlBusy(submit, true, "处理中");
      box.innerHTML = '<div class="alert info">正在生成计划…</div>';
      try {
        const data = await postModelRun(wsUrl("/run"), {
          step: "plan-chapters",
          params: Object.assign({ target_chapters: target }, NOVEL_STAGE_LIMITS["plan-chapters"]),
        });
        await pollJob(data.job_id, box, submit, async () => {
          await refreshReadiness();
        });
      } catch (err) {
        box.innerHTML = renderErrorCard(err);
        setControlBusy(submit, false);
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
        item.setAttribute("aria-pressed", item === btn ? "true" : "false");
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
      const params = {
        chapters: Number(form.elements.chapters.value || 1),
        resume_from: Number(form.elements.resume_from.value || 1),
        max_retries: Number(form.elements.max_retries.value || 2),
        replan_every: Number(form.elements.replan_every.value || 0),
        budget_cny: Number(form.elements.budget_cny.value || 0),
        min_confidence: Number(form.elements.min_confidence.value || 0.7),
        timeout_minutes: Number(form.elements.timeout_minutes ? form.elements.timeout_minutes.value || 0 : 0),
        max_model_requests: Number(form.elements.max_model_requests ? form.elements.max_model_requests.value || 20 : 20),
        tier: form.elements.tier ? form.elements.tier.value || "mid" : "mid",
        auto_advance: Boolean(form.elements.auto_advance.checked),
        require_plan: true,
        require_external_review: true,
      };
      jobBox.innerHTML = '<div class="alert info">正在检查是否可以继续；尚未开始生成。</div>';
      const readiness = await refreshReadiness();
      if (!readiness || ["ready", "warn"].indexOf(readiness.status) === -1) {
        jobBox.innerHTML = '<div class="alert warn">检查未通过，没有开始生成。请先处理就绪检查中的提示。</div>';
        return;
      }
      if (!await confirmPaidAction({
        title: "确认开始续写",
        action: "将按当前写作与评审设置生成正文。",
        scope: "从第 " + params.resume_from + " 章开始，共 " + params.chapters + " 章；最多 " + params.max_model_requests + " 次模型请求；可用额度上限 " + params.budget_cny + " 元；最长等待 " + params.timeout_minutes + " 分钟",
        preservation: "将更新本次范围内的新正文和检查记录；已有内容会保留。开始后可查看进度或请求取消，取消前已保存的内容不会删除。",
      })) return;
      writeBookJobRunning = true;
      setFormSubmitBusy(form, true, "处理中");
      jobBox.innerHTML = '<div class="alert info">正在启动任务；已有设置会保留。</div>';
      try {
        const data = await postModelRun(wsUrl("/run"), { step: "write-book", params });
        await pollJob(data.job_id, jobBox, submit, async () => {
          writeBookJobRunning = false;
          setFormSubmitBusy(form, false);
          await refreshReadiness();
          await refreshRecentJobsSidebar();
        });
      } catch (err) {
        writeBookJobRunning = false;
        jobBox.innerHTML = renderErrorCard(err);
        setFormSubmitBusy(form, false);
      } finally {
        // pollJob deliberately renders and returns on polling transport errors.
        // Always release every submit control (including readiness CTAs using
        // form="write-book-form") even when no terminal job reached afterDone.
        writeBookJobRunning = false;
        setFormSubmitBusy(form, false);
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
        return refreshReadiness();
      }
      panel.innerHTML = renderReadinessPanel(data);
      if (pill) pill.innerHTML = statusBadge(data.status || "blocked");
      const canProceed = data.status === "ready" || data.status === "warn";
      const submitControls = Array.prototype.slice.call(form.querySelectorAll('button[type="submit"]'));
      panel.querySelectorAll('[form="write-book-form"]').forEach(function (control) { submitControls.push(control); });
      submitControls.forEach(function (control) {
        control.disabled = writeBookJobRunning || !canProceed;
        control.title = writeBookJobRunning ? "有任务进行中，请等待完成" : (!canProceed ? "当前状态尚未确认，请先完成就绪检查" : "");
        if (writeBookJobRunning) setControlBusy(control, true, "处理中");
      });
      return data;
    } catch (err) {
      if (requestSeq !== readinessRequestSeq) return;
      panel.innerHTML = renderErrorCard(err);
      if (submit) { submit.disabled = true; submit.title = "续写入口检查失败，请稍后重试"; }
      return null;
    }
  }
  function renderReadinessPanel(data) {
    const blockers = data.blockers || [];
    const warnings = data.warnings || [];
    const status = data.status || "?";
    const canProceed = status === "ready" || status === "warn";
    const primary = data.primary_blocker || null;
    const kind = primary ? primary.kind : "";
    const cfg = ctaConfig(kind, primary || {});
    let html = '<div class="readiness-primary">' +
      '<div class="copy">' +
      '<p class="eyebrow ornament">下一步</p>' +
      '<h3>' + escapeHtml(status === "blocked" ? cfg.label : status === "warn" ? "可以续写，但有提示" : status === "ready" ? "续写入口已就绪" : "状态待确认") + "</h3>" +
      '<p>' + escapeHtml(status === "blocked" ? (cfg.hint || "请先处理阻断项。") : status === "warn" ? "建议看一眼检查提示，但不影响开始写作。" : status === "ready" ? "参数与前置内容都已通过检查。" : "没有开始生成，请刷新状态后再继续。") + "</p>" +
      "</div>" +
      '<div class="cluster">' +
      (status === "blocked" ? renderCtaButton(kind, primary || {}, "btn-primary") : canProceed ? '<button type="submit" form="write-book-form" class="btn btn-paid" data-ui-action="paid">检查并继续</button>' : '<button type="button" class="btn btn-secondary" data-cta-action="reload">刷新状态</button>') +
      "</div>" +
      "</div>";
    html += '<div class="kv-list compact readiness-status-row">' +
      '<div class="k">状态</div><div class="v">' + statusBadge(status) + "</div>" +
      '<div class="k">本次章节数</div><div class="v">' + escapeHtml(String(data.chapters || "?")) + "</div>" +
      '<div class="k">开始章节</div><div class="v">' + escapeHtml(String(data.resume_from || "?")) + "</div>" +
      '<div class="k">下一章</div><div class="v">' + escapeHtml(String(data.next_unapproved_chapter || "—")) + "</div>" +
      '<div class="k">细纲覆盖</div><div class="v">' + escapeHtml(String(data.plan_window || "?")) + "</div>" +
      "</div>";
    const details = [];
    const blockerDetails = groupedReadinessHtml(blockers, readinessReasonText, kind);
    const warningDetails = groupedReadinessHtml(warnings, readinessWarningText, "");
    if (blockerDetails) details.push('<div class="alert error">' + blockerDetails + "</div>");
    if (warningDetails) details.push('<div class="alert warn">' + warningDetails + "</div>");
    html += '<details class="details-fold readiness-diagnostics"><summary>检查详情</summary>' +
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
      '<div class="k">步骤</div><div class="v">' + escapeHtml(stepLabel(job.step)) + "</div>" +
      '<div class="k">状态</div><div class="v">' + (isHistory ? mutedStatusBadge(job.status || "?") : statusBadge(job.status || "?")) + "</div>" +
      '<div class="k">任务编号</div><div class="v"><code>' + escapeHtml((job.job_id || "").slice(0, 12)) + "…</code></div>" +
      (jobActionableSummary(job) ? '<div class="k">说明</div><div class="v">' + escapeHtml(jobActionableSummary(job).slice(0, 120)) + "</div>" : "") +
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
    const failureReason = job.result_summary && job.result_summary.failure_reason;
    const failureCard = failureReason && FRONT_ERROR_CATALOG[failureReason];
    const icon = icons[status] || "•";
    if (status === "succeeded") return icon + " 已完成" + (job.result_summary && job.result_summary.snapshot_path ? " · 快照已就绪" : "");
    return icon + " " + statusLabel(status) + (failureCard ? " · " + failureCard.title : "");
  }
  function jobActionKind(job) {
    const detail = jobBlockedDetail(job);
    const reason = detail && detail.reason ? detail.reason : "";
    if (reason === "retry_exhausted") {
      return job.step === "write-book" && detail && Number(detail.chapter) > 0 ? "retry_exhausted" : "";
    }
    if (CTA_ACTIONS[reason]) return reason;
    if (/fingerprint/.test(reason)) return "plan_fingerprint_stale";
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
  function renderJobPageCta(kind, job) {
    if (!kind) return "";
    if (kind === "retry_exhausted") {
      const chapter = jobChapterNumber(job || {});
      if (!chapter) return "";
      return '<button type="button" class="btn btn-paid btn-sm" data-ui-action="paid" data-cta-action="retry_write_book" data-write-recovery-chapter="' +
        escapeHtml(String(chapter)) + '">查看并恢复</button>';
    }
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
      actions.push('<button type="button" class="btn btn-secondary btn-sm" data-job-partial="' + escapeHtml(String(partial.chapter)) + '">查看临时草稿</button>');
    }
    if (job.status === "succeeded" && chapter) {
      actions.push('<a class="btn btn-secondary btn-sm" href="' + wsHref("/chapter/" + chapter) + '">查看章节</a>');
    }
    const localDemoHref = localDemoTargetHref(job);
    if (job.status === "succeeded" && localDemoHref) {
      actions.push('<a class="btn btn-primary btn-sm" href="' + localDemoHref + '">打开演练交付</a>');
    }
    if (actionKind) actions.push(renderJobPageCta(actionKind, job));
    const retryStatuses = ["succeeded", "failed", "blocked", "aborted", "budget_exceeded"];
    const failureReason = summary && summary.failure_reason;
    if (actionKind !== "retry_exhausted" && job.retryable === true && retryStatuses.indexOf(job.status) >= 0 && failureReason !== "submission_unknown") {
      const paidRetry = isPaidNovelJobStep(job.step);
      actions.push('<button type="button" class="btn ' + (paidRetry ? "btn-paid" : "btn-secondary") +
        ' btn-sm"' + (paidRetry ? ' data-ui-action="paid"' : "") + ' data-job-retry="' +
        escapeHtml(job.job_id || "") + '">重新开始</button>');
    }
    return '<div class="job-drawer">' +
      (job.persistence_degraded === true
        ? '<div class="alert warn">任务状态的持久化记录不完整；请刷新任务页核对，服务重启后可能显示为状态丢失。</div>'
        : '') +
      '<div class="drawer-grid">' +
      '<div class="kv-list compact">' +
      '<div class="k">结果</div><div class="v">' + escapeHtml(jobActionableSummary(job)) + '</div>' +
      '<div class="k">问题编号</div><div class="v">' + escapeHtml(job.trace_id || "—") + (job.trace_id ? " " + copyButton(job.trace_id) : "") + '</div>' +
      '<div class="k">已保存内容</div><div class="v">' + (summary.snapshot_path ? "已保留快照" : "—") + '</div>' +
      '<div class="k">临时草稿</div><div class="v">' + (partial && partial.chapter ? '<button type="button" class="copy-btn" data-job-partial="' + escapeHtml(String(partial.chapter)) + '">第 ' + escapeHtml(String(partial.chapter)) + " 章临时草稿</button>" : "—") + '</div>' +
      '</div>' +
      '<div class="stack">' +
      '<p class="eyebrow">恢复动作</p>' +
      '<div class="cluster">' + (actions.join("") || '<span class="muted">暂无动作</span>') + '</div>' +
      '</div>' +
      '</div>' +
      '</div>';
  }
  function openPartialPreview(chapter) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="partial-title">' +
      '<div class="modal-header" id="partial-title">第 ' + escapeHtml(chapter) + ' 章临时草稿</div>' +
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
      '<a class="btn btn-secondary" download="chapter_' + String(data.chapter || chapter).padStart(2, "0") + '.partial.md" href="' + href + '">下载完整草稿</a>' +
        '<button type="button" class="btn btn-ghost" data-modal-close>关闭</button>';
    }).catch(function (err) {
      body.innerHTML = renderErrorCard(err);
    });
  }
  function confirmPaidRetry(job) {
    return new Promise(function (resolve) {
      let settled = false;
      const backdrop = document.createElement("div");
      backdrop.className = "modal-backdrop";
      backdrop.innerHTML =
        '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="paid-retry-title">' +
        '<div class="modal-header" id="paid-retry-title">确认重新开始</div>' +
        '<div class="modal-body">' +
        '<p>将按原任务范围重新开始“' + escapeHtml(stepLabel(job && job.step)) + '”。</p>' +
        '<div class="alert warn">如果当前启用了真实生成服务，这次操作可能使用人民币额度；原任务和已有内容会保留。</div>' +
        '<p><strong>本次范围：</strong>' + escapeHtml(paidLimitScope("原任务范围", (job && job.params) || {})) + '</p>' +
        '<p>开始后可在任务记录中查看进度或请求取消。</p>' +
        '</div><div class="modal-footer">' +
        '<button type="button" class="btn btn-ghost" data-modal-close>取消</button>' +
        '<button type="button" class="btn btn-paid" data-paid-retry-confirm>确认重新开始</button>' +
        '</div></div>';
      function finish(value) {
        if (settled) return;
        settled = true;
        close();
        resolve(value);
      }
      const close = mountModal(backdrop, {
        initialFocus: backdrop.querySelector("[data-modal-close]"),
        onClose: function () { if (!settled) { settled = true; resolve(false); } },
      });
      backdrop.addEventListener("click", function (ev) {
        if (ev.target === backdrop || ev.target.hasAttribute("data-modal-close")) finish(false);
      });
      backdrop.querySelector("[data-paid-retry-confirm]").addEventListener("click", function () { finish(true); });
    });
  }
  async function retryJob(job, btn) {
    if (!job) return;
    if (isPaidNovelJobStep(job.step) && !await confirmPaidRetry(job)) return;
    setControlBusy(btn, true, "处理中");
    try {
      const data = await postModelRun(wsUrl("/run"), { step: job.step, params: job.params || {} });
      showToast("已重新启动：" + stepLabel(job.step), "info");
      if (data && data.job_id) setTimeout(function () { initJobs(); }, 500);
    } catch (err) {
      showToast("重试失败：" + errTitle(err), "error");
      setControlBusy(btn, false);
    }
  }
  // iter063 A1: render a terminal job failure / blocked state as a friendly
  // error card (human title + cause + CTA) instead of dumping the raw
  // "reason · error" line (e.g. "outline_stale · stale debate outline (…)").
  function renderJobFailureCard(job) {
    const detail = jobBlockedDetail(job);
    const reason = (detail && detail.reason) || "";
    const line = jobFailureLine(job);
    const failureReason = job.result_summary && job.result_summary.failure_reason;
    const failureCard = failureReason && FRONT_ERROR_CATALOG[failureReason];
    if (failureCard) {
      return renderErrorCard({ card: Object.assign({}, failureCard, {
        trace_id: job.trace_id || "",
      })});
    }
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
    const titles = { aborted: "任务已取消", budget_exceeded: "额度不足", lost: "任务状态待确认", blocked: "需要补充内容" };
    const fallback = CTA_ACTIONS[jobActionKind(job)];
    return renderErrorCard({ card: {
      code: job.status || "client_error",
      title: titles[job.status] || "任务未成功",
      cause: (fallback && fallback.hint) || "当前内容已保留。请检查页面提示后调整设置，再由你决定是否重新开始。",
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
        renderJobReconcile(box);
        setControlBusy(submit, false);
        return;
      }
      const disposition = jobPollDisposition(job && job.status);
      if (disposition === "invalid") {
        renderJobReconcile(box);
        setControlBusy(submit, false);
        return null;
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
        '<div class="k">任务编号</div><div class="v"><code>' + escapeHtml(jobId) + "</code></div>" +
        '<div class="k">状态</div><div class="v">' + statusBadge(job.status || "?") + "</div>" +
        '<div class="k">当前步骤</div><div class="v">' + escapeHtml(currentStepLabel(job.current_step, job.step, job.status)) + "</div>" +
        '<div class="k">进度</div><div class="v">' + pct + "%</div>" +
        "</div>" +
        '<div class="progress"><div class="progress-fill" style="width:' + pct + '%"></div></div>' +
        '<div class="form-actions" style="margin-top:8px">' +
        '<button type="button" class="btn btn-ghost btn-sm" data-cancel-job="' + escapeHtml(jobId) + '"' + (cancelPending ? " disabled" : "") + ">取消任务</button>" +
        ' <a class="btn btn-ghost btn-sm" data-leave-guard href="' + wsHref("/jobs") + '">任务页</a>' +
        "</div>" +
        (cancelPending
          ? '<div class="alert warn" style="margin-top:6px">已请求取消 · 当前步骤「' + escapeHtml(currentStepLabel(job.current_step, job.step, job.status)) + "」" + waited + "；最多再等当前一次不可中断调用或本地子进程结束。</div>"
          : "") +
        (job.persistence_degraded === true
          ? '<div class="alert warn" style="margin-top:6px">任务状态的持久化记录不完整；请打开任务页核对。</div>'
          : "");
      if (disposition === "terminal") {
        const partial = job.result_summary && job.result_summary.partial;
        if (partial && partial.chapter) {
          const label = "第 " + String(partial.chapter) + " 章临时草稿";
          box.innerHTML += '<div class="alert warn" style="margin-top:8px">已保留临时草稿：' +
            '<a href="' + wsUrl("/draft/" + partial.chapter + "?variant=partial") + '">' +
            escapeHtml(label) + "</a></div>";
        }
        setControlBusy(submit, false);
        const finishedStepLabel = stepLabel(job.step || job.current_step);
        if (job.status === "succeeded") {
          showToast(finishedStepLabel + "已完成", "info");
        } else {
          // iter063 A1: friendly card (incl. CTA) instead of a raw reason dump.
          box.innerHTML += renderJobFailureCard(job);
          // Toast title mirrors the card: a direct readiness-kind label, else
          // the bare status (don't claim a fallback kind the card doesn't show).
          const d = jobBlockedDetail(job);
          const direct = CTA_ACTIONS[(d && d.reason) || ""];
          showToast(finishedStepLabel + " · " + (direct ? direct.label : statusLabel(job.status)), "error");
        }
        if (afterDone) await afterDone(job);
        return job;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  function jobPollDisposition(status) {
    if (status === "pending" || status === "running") return "active";
    if (["succeeded", "blocked", "failed", "aborted", "lost", "budget_exceeded"].indexOf(status) >= 0) return "terminal";
    return "invalid";
  }
  function renderJobReconcile(box) {
    box.innerHTML = '<div class="alert warn">任务状态无法确认，已停止自动刷新。请刷新或前往任务页核对。</div>' +
      '<div class="cluster"><a class="btn btn-secondary btn-sm" data-leave-guard href="' + wsHref("/jobs") + '">打开任务页</a>' +
      '<a class="btn btn-ghost btn-sm" href="">刷新页面</a></div>';
  }

  // ===== page: full-text search (iter075) =================================
  // XSS 安全高亮的根：后端只回原始片段文本 + 整数 offsets；这里全程用 DOM
  // (createElement/createTextNode) 构建，绝不 innerHTML 拼正文/用户输入。即使
  // 正文含 <script>/<img onerror> 也只当纯文本渲染。
  const SEARCH_SOURCE_LABELS = { original: "原文章节", draft: "续写章节", kb: "人物与故事资料" };

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
    const source = Object.prototype.hasOwnProperty.call(SEARCH_SOURCE_LABELS, hit && hit.source) ? hit.source : "unknown";
    badge.className = "badge source-" + source;
    badge.textContent = SEARCH_SOURCE_LABELS[source] || "来源待确认";
    head.appendChild(badge);
    let titleEl;
    titleEl = document.createElement("span");
    titleEl.className = "search-hit-title";
    titleEl.textContent = typeof hit.title === "string" && hit.title.trim() ? hit.title.slice(0, 160) : "未命名内容";
    head.appendChild(titleEl);
    const count = document.createElement("span");
    count.className = "search-hit-count";
    count.textContent = safePublicCount(hit.match_count) + " 处";
    head.appendChild(count);
    card.appendChild(head);
    const snippets = Array.isArray(hit.snippets) ? hit.snippets : [];
    for (let i = 0; i < snippets.length; i++) {
      const p = document.createElement("p");
      p.className = "search-snippet";
      p.appendChild(buildSnippet(snippets[i]));
      card.appendChild(p);
    }
    const action = document.createElement("a");
    action.className = "btn btn-secondary search-hit-open";
    if (source === "draft" && Number.isSafeInteger(Number(hit.chapter_no)) && Number(hit.chapter_no) > 0) {
      action.href = wsHref("/chapter/" + Number(hit.chapter_no));
    } else if (source === "kb") {
      action.href = wsHref("/plan");
    } else {
      action.href = wsHref("/chapters");
    }
    action.textContent = "打开";
    card.appendChild(action);
    return card;
  }

  async function initSearch() {
    const input = document.getElementById("search-input");
    const box = document.getElementById("search-results");
    const summary = document.getElementById("search-summary");
    const sourcesBox = document.getElementById("search-sources");
    const clearButton = document.getElementById("search-clear");
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
        if (mine === seq) {
          box.innerHTML = publicLoadError("搜索没有完成", "已有本地内容不受影响。请保持当前条件并重试。", '<button type="button" class="btn btn-secondary" data-search-retry>重试搜索</button>');
          summary.textContent = "";
          const retry = box.querySelector("[data-search-retry]");
          if (retry) retry.addEventListener("click", function () { run(true); });
        }
        return;
      }
      if (mine !== seq) return;                  // 已被更新的查询覆盖，丢弃旧响应
      const hits = data.hits || [];              // 后端已按 sources 过滤，无需客户端二次过滤
      if (!hits.length) {
        summary.textContent = "";
        showEmpty("没有找到符合条件的内容", "当前关键词：“" + q + "”；范围：" + active.map(function (item) { return SEARCH_SOURCE_LABELS[item] || "来源待确认"; }).join("、") + "。可调整条件或清除筛选。");
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
    if (clearButton) clearButton.addEventListener("click", function () {
      clearTimeout(timer); ++seq; input.value = "";
      if (sourcesBox) sourcesBox.querySelectorAll("input").forEach(function (item) { item.checked = true; });
      summary.textContent = ""; syncUrl("", selectedSources());
      showEmpty("输入关键词开始搜索", "可在章节、人物和故事资料中组合查找。");
      input.focus();
    });

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
      renderChapters(box, Array.isArray(drafts.drafts) ? drafts.drafts : [], Array.isArray(manifest.chapters) ? manifest.chapters : [], reviewByCh);
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
    for (const d of drafts) {
      const r = reviewByCh.get(d.chapter) || {};
      const chapterNo = Number.isInteger(Number(d.chapter)) && Number(d.chapter) > 0 ? Number(d.chapter) : 0;
      if (!chapterNo) continue;
      const id = "第 " + chapterNo + " 章";
      const title = typeof r.title === "string" && r.title.trim() ? r.title.trim().slice(0, 120) : id;
      const isPartial = d.variant === "partial";
      const detailHref = isPartial ? wsUrl("/draft/" + chapterNo + "?variant=partial") : "/w/" + encodeURIComponent(ws) + "/chapter/" + chapterNo;
      const state = isPartial ? "需要处理" : statusLabel(d.review_verdict || d.verdict || "unknown");
      const updated = publicDateLabel(typeof d.updated_at === "string" ? d.updated_at : "");
      rows.push(
        '<article class="chapter-item" data-chapter-item data-source="drafts" data-number="' + chapterNo + '" data-title="' + escapeHtml(title) + '" data-id="' + escapeHtml(id) + '">' +
        '<div class="chapter-item-main"><div class="cluster"><span class="badge no-dot badge-novel">续写章节</span>' + statusBadge(isPartial ? "blocked" : (d.review_verdict || d.verdict || "unknown")) + '</div>' +
        '<h2>' + escapeHtml(title) + '</h2><p class="muted">' + escapeHtml(id) + ' · ' + escapeHtml(String(safePublicCount(d.chars))) + ' 字</p></div>' +
        '<dl class="chapter-item-meta"><div><dt>来源</dt><dd>续写章节</dd></div><div><dt>状态</dt><dd>' + escapeHtml(state) + '</dd></div><div><dt>更新时间</dt><dd>' + escapeHtml(updated) + '</dd></div></dl>' +
        '<div class="chapter-item-action">' + (isPartial
          ? '<a class="btn btn-secondary" href="' + detailHref + '">查看临时内容</a>'
          : '<a class="btn btn-primary" href="' + detailHref + '">打开章节</a>') + '</div></article>'
      );
    }
    manifest.forEach(function (ch, index) {
      const title = typeof ch.title === "string" && ch.title.trim() ? ch.title.trim().slice(0, 120) : "原文章节 " + (index + 1);
      rows.push(
        '<article class="chapter-item source" data-chapter-item data-source="source" data-number="' + (index + 1) + '" data-title="' + escapeHtml(title) + '" data-id="原文章节">' +
        '<div class="chapter-item-main"><div class="cluster"><span class="badge no-dot">原文章节</span><span class="badge no-dot">只读</span></div><h2>' + escapeHtml(title) + '</h2><p class="muted">' + escapeHtml(String(safePublicCount(ch.char_count))) + ' 字</p></div>' +
        '<dl class="chapter-item-meta"><div><dt>来源</dt><dd>原文章节</dd></div><div><dt>状态</dt><dd>只读</dd></div><div><dt>更新时间</dt><dd>随原文导入</dd></div></dl>' +
        '<div class="chapter-item-action"><span class="btn btn-ghost" aria-disabled="true">原文只读</span></div></article>'
      );
    });
    box.innerHTML = '<div class="chapter-items" id="chapters-data-table">' + rows.join("") + '</div><div id="chapters-empty-filter" hidden></div>';
  }
  function bindChapterFilter() {
    const search = document.getElementById("chapter-search");
    const toggles = document.querySelectorAll(".filter-toggle .btn");
    const sort = document.getElementById("chapter-sort");
    const clear = document.getElementById("chapter-clear-filter");
    const live = document.getElementById("chapter-filter-status");
    let mode = "all";
    function apply() {
      const q = (search && search.value || "").trim().toLowerCase();
      const items = Array.from(document.querySelectorAll("[data-chapter-item]"));
      if (sort && sort.value === "number") items.sort(function (a, b) { return Number(a.dataset.number) - Number(b.dataset.number); });
      else items.sort(function (a, b) { return Number(b.dataset.number) - Number(a.dataset.number); });
      const parent = document.getElementById("chapters-data-table");
      items.forEach(function (item) { if (parent) parent.appendChild(item); });
      let shown = 0;
      items.forEach((tr) => {
        const isSource = tr.dataset.source === "source";
        const title = (tr.dataset.title || "").toLowerCase();
        const id = (tr.dataset.id || "").toLowerCase();
        const matchesQuery = !q || title.includes(q) || id.includes(q);
        let matchesMode = true;
        if (mode === "drafts") matchesMode = !isSource;
        else if (mode === "source") matchesMode = isSource;
        const visible = matchesQuery && matchesMode;
        tr.hidden = !visible;
        if (visible) shown += 1;
      });
      const empty = document.getElementById("chapters-empty-filter");
      if (empty) {
        empty.hidden = shown !== 0;
        empty.innerHTML = shown ? "" : emptyState("没有符合条件的章节", "当前条件：" + (q ? "关键词“" + q + "”；" : "") + ({ all: "全部来源", drafts: "续写章节", source: "原文章节" }[mode] || "全部来源"), '<button type="button" class="btn btn-secondary" data-clear-chapter-filter>清除筛选</button>');
      }
      if (live) live.textContent = "显示 " + shown + " 个章节。";
    }
    if (search) search.addEventListener("input", apply);
    if (sort) sort.addEventListener("change", apply);
    function reset() {
      if (search) search.value = "";
      mode = "all";
      toggles.forEach(function (b) { b.classList.toggle("active", b.dataset.mode === "all"); });
      if (sort) sort.value = "newest";
      apply();
      if (search) search.focus();
    }
    if (clear) clear.addEventListener("click", reset);
    document.addEventListener("click", function (ev) { if (ev.target.closest("[data-clear-chapter-filter]")) reset(); });
    toggles.forEach((btn) => {
      btn.addEventListener("click", () => {
        toggles.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        mode = btn.dataset.mode || "all";
        apply();
      });
    });
    apply();
  }

  // ===== page: chapter detail ============================================
  let chapterDetailRequest = 0;
  async function refreshChapterDetail(num) {
    const request = ++chapterDetailRequest;
    try {
      const data = await fetchJson(wsUrl("/draft/" + num));
      if (request === chapterDetailRequest) renderChapterDetail(data);
    } catch (err) {
      if (request === chapterDetailRequest) throw err;
    }
  }
  async function initChapterDetail() {
    bindHashTabs();
    bindLintJump();
    const num = window.CHAPTER_NO;
    if (!num) return;
    bindDraftEditor(num);
    try {
      await refreshChapterDetail(num);
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
    function saveState(text, kind) {
      if (!statusBox) return;
      statusBox.className = "save-state " + (kind || "");
      statusBox.textContent = text;
    }
    area.addEventListener("input", function () { area.dataset.dirty = "1"; saveState("有尚未保存的修改", "warn"); });
    async function saveDraft() {
      if (area.dataset.loaded !== "1") throw new Error("正文尚未加载成功");
      const content = area.value;
      if (!content.trim()) {
        saveState("没有保存成功。正文不能为空，修改仍保留。", "error");
        showToast("正文不能为空", "error");
        return null;
      }
      const submitted = captureEditSnapshot(area);
      ++chapterDetailRequest;
      const res = await putJson(wsUrl("/draft/" + num), { content: content, expected_sha256: area.dataset.version });
      area.dataset.version = res.draft_sha256;
      if (!acknowledgeEditSnapshot(submitted)) { saveState("已保存提交时的正文；仍有新的修改尚未保存", "warn"); return null; }
      return res;
    }
    area._saveBeforeLeave = async function () {
      saveBtn.disabled = true;
      saveReviewBtn.disabled = true;
      saveState("正在保存", "busy");
      try {
        const res = await saveDraft();
        if (!res) return false;
        saveState("已保存", "success");
        showToast("第 " + num + " 章已保存；内容检查需要更新", "info");
        return true;
      } catch (err) {
        saveState("没有保存成功。正文可能已在别处更新；修改仍保留，请先复制备份并重新加载核对。", "error");
        return false;
      } finally {
        saveBtn.disabled = false;
        saveReviewBtn.disabled = false;
      }
    };
    registerDirtyEditor("draft", {
      label: "正文",
      isDirty: function () { return area.isConnected && area.dataset.dirty === "1"; },
      save: area._saveBeforeLeave,
      discard: function () { delete area.dataset.dirty; },
      focus: function () { area.focus(); },
    });
    saveBtn.addEventListener("click", async function () {
      setControlBusy(saveBtn, true, "正在保存");
      const saved = await area._saveBeforeLeave();
      setControlBusy(saveBtn, false);
      if (saved) {
        await refreshChapterDetail(num);
      }
    });
    saveReviewBtn.addEventListener("click", async function () {
      if (!area.value.trim()) {
        saveState("没有保存成功。正文不能为空，修改仍保留。", "error");
        showToast("正文不能为空", "error");
        return;
      }
      if (!await confirmPaidAction({
        title: "确认保存并重新检查",
        action: "将保存当前正文并重新进行本章内容检查。",
        scope: paidLimitScope("第 " + num + " 章", NOVEL_STAGE_LIMITS["write-book"]),
        preservation: "当前正文会先保存；原评审记录不会覆盖正文。",
      })) return;
      saveBtn.disabled = true;
      setControlBusy(saveReviewBtn, true, "正在保存");
      saveState("正在保存", "busy");
      let draftSaved = false;
      try {
        const res = await saveDraft();
        if (!res) return;
        draftSaved = true;
        saveState("已保存，正在检查", "busy");
        const job = await postModelRun(wsUrl("/run"), {
          step: "review-chapter",
          params: Object.assign({ chapter: Number(num) }, NOVEL_STAGE_LIMITS["write-book"]),
        });
        await pollJob(job.job_id, statusBox, null, async function () {
          await refreshChapterDetail(num);
        });
      } catch (err) {
        saveState(draftSaved
          ? "已保存，但检查没有开始。可以再次选择重新检查。"
          : "没有保存成功。编辑内容仍保留，请重试。", draftSaved ? "warn" : "error");
      } finally {
        saveBtn.disabled = false;
        setControlBusy(saveReviewBtn, false);
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
    if (!rewriteTriggered && !(rewriteMeta && rewriteMeta.style_drift_unresolved === true)) return "";
    return '<h4>定向改写复测</h4>' +
      '<div class="kv-list compact">' +
      '<div class="k">结果</div><div class="v">' +
        (rewriteMeta && rewriteMeta.style_drift_unresolved === true ? "仍需调整" : "已完成") +
        (rewriteMeta && rewriteMeta.style_rewrite_applied === true ? " · 已采用" : " · 已回退") + "</div>" +
      '<div class="k">调整前</div><div class="v">' + (before ? styleDriftBadge(before) : "—") + "</div>" +
      '<div class="k">调整后</div><div class="v">' + (after ? styleDriftBadge(after) : "—") + "</div>" +
      '<div class="k">改善幅度</div><div class="v">' +
        (Number.isFinite(improvement) ? escapeHtml(improvement.toFixed(3)) : "—") + "</div>" +
      '<div class="k">是否仍需调整</div><div class="v">' +
        (rewriteMeta && rewriteMeta.style_drift_unresolved === true ? "是" : "否") + "</div>" +
      "</div>";
  }
  function renderStyleDriftPanel(drift, fingerprint, baselineHash, rewriteMeta) {
    const rewriteHtml = renderStyleRewriteAudit(rewriteMeta);
    if (!isPlainObject(drift) || !drift.status) {
      return '<div class="stack"><p class="muted">本章暂无文风漂移检测记录。</p>' + rewriteHtml + "</div>";
    }
    const score = drift.style_drift_score == null ? "—" : fmtStyleNumber(drift.style_drift_score, 3);
    const top = Array.isArray(drift.top_dimensions) ? drift.top_dimensions.filter(isPlainObject) : [];
    const skipped = Array.isArray(drift.skipped_dimensions) ? drift.skipped_dimensions.filter(isPlainObject) : [];
    const rows = top.map((d, index) => (
      "<tr>" +
      "<td>写作特征 " + (index + 1) + "</td>" +
      "<td>" + fmtStyleNumber(d.current_value, 3) + "</td>" +
      "<td>" + fmtStyleNumber(d.baseline_value, 3) + "</td>" +
      "<td>" + fmtStyleNumber(d.tolerance, 3) + "</td>" +
      "<td>" + fmtStyleNumber(d.normalized_delta, 3) + "</td>" +
      "<td>" + fmtStyleNumber(d.dimension_score, 3) + "</td>" +
      "</tr>"
    )).join("");
    const skippedHtml = skipped.length
      ? '<div class="muted">有 ' + skipped.length + ' 项写作特征暂未比较。</div>'
      : "";
    const table = rows
      ? tableScroll('<table><thead><tr><th>特征</th><th>当前</th><th>参考</th><th>容差</th><th>偏差</th><th>评分</th></tr></thead><tbody>' + rows + '</tbody></table>')
      : '<p class="muted">暂无可比较维度。</p>';
    return '<div class="stack">' +
      '<div class="kv-list compact">' +
      '<div class="k">偏离程度</div><div class="v">' + styleDriftBadge(drift) + "</div>" +
      '<div class="k">综合评分</div><div class="v">' + escapeHtml(score) + "</div>" +
      '<div class="k">检查状态</div><div class="v">' + (drift.status === "skipped" ? "未检查" : "已检查") + "</div>" +
      '<div class="k">参考风格</div><div class="v">' + (fingerprint ? "已建立" : "未建立") + "</div>" +
      '</div>' +
      '<h4>偏离最高维度</h4>' +
      table +
      skippedHtml +
      rewriteHtml +
      "</div>";
  }
  function renderChapterDetail(data) {
    const meta = isPlainObject(data && data.meta) ? data.meta : {};
    const review = isPlainObject(data && data.review) ? data.review : {};
    const num = safeOptionalCount(data && data.chapter);
    const editArea = document.getElementById("draft-edit-area");
    const saveBtn = document.getElementById("draft-save");
    const saveReviewBtn = document.getElementById("draft-save-review");
    if (!data || typeof data.content !== "string" || typeof data.draft_sha256 !== "string") throw new Error("正文加载数据不完整");
    if (editArea) {
      editArea.disabled = false;
      editArea.placeholder = "";
    }
    if (saveBtn) saveBtn.disabled = false;
    if (saveReviewBtn) saveReviewBtn.disabled = false;
    // header bar
    const head = document.getElementById("chapter-meta-bar");
    if (head) {
      const rewriteCount = safeOptionalCount(meta.rewrite_count);
      const charCount = safeOptionalCount(meta.chinese_char_count);
      head.innerHTML =
        verdictBadge(meta.verdict || review.verdict) +
        styleDriftBadge(meta.style_drift) +
        styleRewriteBadge(meta) +
        '<span class="badge no-dot">重写 ' + (rewriteCount == null ? "—" : rewriteCount) + " 次</span>" +
        '<span class="badge no-dot">' + (charCount == null ? "—" : charCount) + " 字</span>" +
        (meta.needs_human_review === true ? '<span class="badge warn">需复核</span>' : "");
    }
    // edit tab — populate unless the user is mid-edit (mirrors outline-md)
    if (editArea && !editArea.dataset.dirty && (editArea.dataset.loaded !== "1" || document.activeElement !== editArea)) {
      editArea.value = data.content;
      editArea.dataset.version = data.draft_sha256;
    }
    if (editArea) editArea.dataset.loaded = "1";
    // body — render as paragraphs
    const body = document.getElementById("chapter-body");
    if (body) {
      const lines = (typeof data.content === "string" ? data.content : "").split(/\\n/);
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
      const candidates = Array.isArray(review.agent_reviews) ? review.agent_reviews : (Array.isArray(meta.agent_reviews) ? meta.agent_reviews : []);
      const agents = candidates.filter(isPlainObject);
      if (!agents.length) {
        reviewsBox.innerHTML = '<p class="muted">本章暂无评审记录。</p>';
      } else {
        reviewsBox.innerHTML = agents.map(renderAgentReview).join("");
      }
    }
    // 文字检查 tab
    const lintBox = document.getElementById("tab-lint");
    if (lintBox) {
      const issues = Array.isArray(meta.lint_issues) ? meta.lint_issues.filter(isPlainObject) : [];
      if (!issues.length) {
        lintBox.innerHTML = '<p class="muted">没有文字检查提示。</p>';
      } else {
        const byRule = new Map();
        for (const it of issues) {
          const k = it.rule_id || it.rule || it.type || "misc";
          if (!byRule.has(k)) byRule.set(k, []);
          byRule.get(k).push(it);
        }
        const groups = [];
        for (const [_rule, list] of byRule.entries()) {
          groups.push(
            '<div class="lint-group">' +
            '<h4>检查项 · ' + list.length + "</h4>" +
            "<ul>" +
            list.map((it) => {
              const anchorLine = _extractIssueLine(it);
              return '<li' + (anchorLine != null ? ' class="link-cell" data-jump-line="' + anchorLine + '"' : "") + '>' +
                '<span class="severity ' + escapeHtml((it.severity || "").toLowerCase()) + '">' +
                escapeHtml({ low: "提示", info: "提示", mid: "注意", warn: "注意", high: "重要", error: "重要" }[String(it.severity || "").toLowerCase()] || "状态待确认") + '</span>' +
                '<span>' + escapeHtml(typeof it.message === "string" ? it.message : "此处需要检查") + '</span>' +
                (anchorLine != null ? '<span class="anchor">第 ' + anchorLine + ' 行</span>' : '') +
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
    // 修改建议 tab
    const advBox = document.getElementById("tab-advisor");
    if (advBox) {
      const suggestions = Array.isArray(meta.rewrite_suggestions)
        ? meta.rewrite_suggestions.filter(isPlainObject)
        : [];
      if (!suggestions.length) {
        advBox.innerHTML = '<p class="muted">暂无改写建议。</p>';
      } else {
        advBox.innerHTML = '<div class="stack">' + suggestions.map((s) => (
          '<div class="advisor-item">' +
          '<span class="type">修改建议</span>' +
          '<div class="section">' + escapeHtml(typeof s.section === "string" ? s.section : "（整段）") + "</div>" +
          '<div class="guidance">' + escapeHtml(typeof s.guidance === "string" ? s.guidance : "") + "</div>" +
          "</div>"
        )).join("") + "</div>";
      }
    }
    // history tab (iter 074: + 多版本草稿 diff)
    const histBox = document.getElementById("tab-history");
    if (histBox) {
      const historyRewriteCount = safeOptionalCount(meta.rewrite_count);
      const historyRewriteRound = safeOptionalCount(meta.rewrite_round);
      histBox.innerHTML =
        '<div class="kv-list compact">' +
        '<div class="k">重写次数</div><div class="v">' + (historyRewriteCount == null ? "—" : historyRewriteCount) + "</div>" +
        '<div class="k">重写轮次</div><div class="v">' + (historyRewriteRound == null ? "—" : historyRewriteRound) + "</div>" +
        '<div class="k">是否润色</div><div class="v">' + (meta.polish_applied === true ? "是" : meta.polish_applied === false ? "否" : "状态待确认") + "</div>" +
        '<div class="k">历史快照</div><div class="v">' + (typeof meta.snapshot_path === "string" && meta.snapshot_path ? "已保留" : "无") + "</div>" +
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
        (v.verdict ? "（" + escapeHtml(verdictLabel(v.verdict)) + "）" : "") + "</option>";
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
    const scores = isPlainObject(a.scores) ? a.scores : {};
    const legacyScores = isPlainObject(a.sub_scores) ? a.sub_scores : {};
    const sub = Object.keys(scores).length ? scores : legacyScores;
    const scoreLabels = { plot: "剧情", prose: "文笔", fidelity: "设定一致性" };
    const bars = ["plot", "prose", "fidelity"].map((k) => {
      const v = sub[k];
      const numeric = finiteStyleNumber(v);
      const bounded = numeric == null ? null : Math.max(0, Math.min(10, numeric));
      const pct = bounded == null ? 0 : bounded * 10;
      return '<div class="subscore-bar"><span class="label">' + scoreLabels[k] + "</span>" +
        '<div class="track"><i style="width:' + pct + '%"></i></div>' +
        '<span class="val">' + (bounded == null ? "—" : escapeHtml(bounded.toFixed(1))) + "</span></div>";
    }).join("");
    const issueItems = Array.isArray(a.issues) ? a.issues : [];
    const issues = issueItems.slice(0, 6).map(function (it) {
      if (typeof it === "string" && it.trim()) return "<li>" + escapeHtml(it.trim()) + "</li>";
      if (it && typeof it === "object") {
        const text = [it.guidance, it.description, it.issue].find(function (value) {
          return typeof value === "string" && value.trim();
        });
        return "<li>" + escapeHtml(text ? text.trim() : "有一项评审建议需要处理") + "</li>";
      }
      return "<li>有一项评审建议需要处理</li>";
    }).join("");
    return (
      '<div class="review-card">' +
      '<div><div class="name">评审角色</div>' +
      '<div class="verdict">' + verdictBadge(a.verdict) +
      '<span class="muted" style="margin-left:6px">评分 ' + (finiteStyleNumber(a.score) == null ? "—" : escapeHtml(finiteStyleNumber(a.score).toFixed(1))) + "</span></div></div>" +
      '<div class="stack">' + bars +
      (issues ? '<details><summary class="muted">问题（' + issueItems.length + "）</summary><ul>" + issues + "</ul></details>" : "") +
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
      const chs = Array.isArray(data.chapters) ? data.chapters.filter(function (item) {
        return item && typeof item === "object" && Number.isSafeInteger(Number(item.chapter)) && Number(item.chapter) > 0;
      }) : [];
      if (!chs.length) {
        box.innerHTML = emptyState("尚无评审记录", "生成草稿后这里会列出每章评审结果。", "");
        return;
      }
      const rows = chs.map((c) => {
        const detail = "/w/" + encodeURIComponent(ws) + "/chapter/" + c.chapter;
        const issueRows = [];
        const agentRows = Array.isArray(c.agent_reviews) ? c.agent_reviews.filter(function (item) { return item && typeof item === "object" && !Array.isArray(item); }) : [];
        agentRows.forEach(function (review) {
          (Array.isArray(review.issues) ? review.issues : []).slice(0, 20).forEach(function (issue) { issueRows.push({ issue: issue, fallback: "context" }); });
        });
        (Array.isArray(c.lint_issues) ? c.lint_issues : []).slice(0, 20).forEach(function (issue) { issueRows.push({ issue: issue, fallback: "prose" }); });
        (Array.isArray(c.rewrite_suggestions) ? c.rewrite_suggestions : []).slice(0, 20).forEach(function (issue) { issueRows.push({ issue: issue, fallback: "context" }); });
        if (!issueRows.length && c.needs_human_review === true) issueRows.push({ issue: {}, fallback: "context" });
        if (!issueRows.length) {
          return '<article class="review-issue-card card"><div class="card-header"><div><p class="eyebrow ornament">第 ' + Number(c.chapter) + ' 章</p><h2>未发现需要查看的问题</h2></div><span class="badge no-dot">已检查</span></div>' +
            '<div class="card-body"><p>已保存的检查记录中暂无人物、时间、地点、设定或前后文问题。</p></div>' +
            '<div class="card-footer"><a class="btn btn-secondary" href="' + detail + '#review">查看位置</a></div></article>';
        }
        return issueRows.map(function (entry, index) {
          const raw = entry.issue && typeof entry.issue === "object" && !Array.isArray(entry.issue) ? entry.issue : {};
          const key = [raw.category, raw.type, raw.rule_id].filter(function (value) { return typeof value === "string"; }).join(" ").toLowerCase();
          let category = entry.fallback;
          if (/person|character|relationship|人物|角色|关系/.test(key)) category = "person";
          else if (/time|chron|时间|时序/.test(key)) category = "time";
          else if (/place|location|地点|场景/.test(key)) category = "place";
          else if (/setting|canon|world|fidelity|设定|世界/.test(key)) category = "setting";
          const labels = {
            person: ["人物关系需要确认", "人物身份、关系或行为与已保存设定可能不一致。"],
            time: ["时间顺序需要确认", "事件先后或时间衔接需要回到正文核对。"],
            place: ["地点信息需要确认", "场景位置或人物所在地点需要回到正文核对。"],
            setting: ["故事设定需要确认", "本章内容与已保存的世界或人物设定可能不一致。"],
            prose: ["文字表达需要确认", "文字表达中有一处需要回到正文查看。"],
            context: ["前后文需要确认", "本章与前后章节的承接有一处需要查看。"],
          };
          const sev = typeof raw.severity === "string" ? raw.severity.toLowerCase() : "";
          const severity = /critical|blocker|major|high|严重|高/.test(sev) ? "严重" : /minor|medium|warn|一般|中/.test(sev) ? "一般" : /info|low|提示|低/.test(sev) ? "提示" : "程度待确认";
          const rawState = typeof raw.status === "string" ? raw.status.toLowerCase() : "";
          const state = !rawState || /open|pending|unresolved|需要查看/.test(rawState) ? "需要查看" : /resolved|closed|已检查/.test(rawState) ? "已检查" : "状态待确认";
          const copy = labels[category] || labels.context;
          return '<article class="review-issue-card card">' +
            '<div class="card-header"><div><p class="eyebrow ornament">第 ' + Number(c.chapter) + ' 章 · 问题 ' + (index + 1) + '</p><h2>' + copy[0] + '</h2></div>' +
            '<div class="cluster"><span class="badge no-dot">严重程度：' + severity + '</span><span class="badge no-dot">' + state + '</span></div></div>' +
            '<div class="card-body"><p>' + copy[1] + '</p><dl class="review-safe-meta"><div><dt>对应位置</dt><dd>第 ' + Number(c.chapter) + ' 章</dd></div><div><dt>处理状态</dt><dd>' + state + '</dd></div></dl></div>' +
            '<div class="card-footer"><a class="btn btn-secondary" href="' + detail + '#review">查看位置</a></div></article>';
        }).join("");
      }).join("");
      box.innerHTML = '<div class="review-issue-list">' + rows + '</div>';
    } catch (err) {
      box.innerHTML = publicLoadError("内容检查没有读取成功", "已保存章节不受影响。请重新加载后再查看。", '<button type="button" class="btn btn-secondary" data-cta-action="reload">重新加载</button>');
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
      renderCostByChapter(costBox, Array.isArray(data.cost_by_chapter) ? data.cost_by_chapter : []);
      renderCacheByModel(cacheBox, Array.isArray(data.cache_by_model) ? data.cache_by_model : []);
      renderSubscores(subBox, Array.isArray(data.subscores) ? data.subscores : []);
    } catch (err) {
      costBox.innerHTML = publicLoadError("创作数据没有读取成功", "已保存记录不受影响。请重新加载后再查看。", '<button type="button" class="btn btn-secondary" data-cta-action="reload">重新加载</button>');
      cacheBox.innerHTML = "";
      subBox.innerHTML = "";
    }
  }

  function renderCostByChapter(box, rows) {
    const safeRows = rows.filter(function (r) { return r && typeof r === "object" && Number.isSafeInteger(Number(r.chapter)) && Number(r.chapter) > 0; });
    if (!safeRows.length) { box.innerHTML = '<p class="muted">暂无可汇总记录。</p>'; return; }
    const knownCosts = safeRows.map(function (r) { return typeof r.cost_cny === "number" && Number.isFinite(r.cost_cny) && r.cost_cny >= 0 ? r.cost_cny : null; }).filter(function (value) { return value != null; });
    const max = knownCosts.length ? Math.max.apply(null, knownCosts.concat([0.001])) : 1;
    const lines = safeRows.map((r) => {
      const cost = r.cost_cny;
      const knownCost = typeof cost === "number" && Number.isFinite(cost) && cost >= 0;
      const pct = knownCost ? Math.round((cost / max) * 100) : 0;
      return (
        '<div style="display:grid;grid-template-columns:56px 1fr 80px;gap:8px;align-items:center;margin-bottom:6px">' +
        '<span class="muted" style="text-align:right">第 ' + r.chapter + ' 章</span>' +
        '<div class="progress" style="height:14px"><div class="progress-fill" style="width:' + pct + '%"></div></div>' +
        '<span class="insight-value">' + (knownCost ? '¥' + cost.toFixed(3) : '费用待确认') +
        ' · ' + safePublicCount(r.calls) + ' 条记录</span>' +
        '</div>'
      );
    }).join("");
    box.innerHTML = lines;
  }

  function renderCacheByModel(box, rows) {
    const safeRows = rows.filter(function (r) { return r && typeof r === "object"; });
    if (!safeRows.length) { box.innerHTML = '<p class="muted">暂无可汇总记录。</p>'; return; }
    const lines = safeRows.map((r, index) => {
      const ratio = r.hit_ratio;
      const pct = typeof ratio === "number" && Number.isFinite(ratio) && ratio >= 0 && ratio <= 1 ? Math.round(ratio * 100) : null;
      return (
        '<div class="kv-list compact" style="margin-bottom:8px">' +
        '<div class="k">生成配置</div><div class="v">配置 ' + (index + 1) + '</div>' +
        '<div class="k">保存记录</div><div class="v">' + safePublicCount(r.calls) + ' 条</div>' +
        '<div class="k">缓存复用比例</div><div class="v">' +
        '<div class="progress" style="display:inline-block;width:120px;vertical-align:middle">' +
        '<div class="progress-fill" style="width:' + (pct == null ? 0 : pct) + '%"></div></div> ' + (pct == null ? '比例待确认' : pct + '%') + '</div>' +
        '</div>'
      );
    }).join("");
    box.innerHTML = lines;
  }

  function renderSubscores(box, rows) {
    const safeRows = rows.filter(function (r) { return r && typeof r === "object" && Number.isSafeInteger(Number(r.chapter)) && Number(r.chapter) > 0; });
    if (!safeRows.length) { box.innerHTML = '<p class="muted">暂无可汇总记录。</p>'; return; }
    const score = (v) => {
      if (typeof v !== "number" || !Number.isFinite(v)) return "暂无记录";
      return v.toFixed(2);
    };
    box.innerHTML = '<div class="insight-score-list">' + safeRows.map(function (r) {
      return '<article class="insight-score-card"><h3>第 ' + Number(r.chapter) + ' 章</h3><dl>' +
        '<div><dt>剧情</dt><dd>' + score(r.plot) + '</dd></div>' +
        '<div><dt>文笔</dt><dd>' + score(r.prose) + '</dd></div>' +
        '<div><dt>设定一致性</dt><dd>' + score(r.fidelity) + '</dd></div>' +
        '<div><dt>综合结果</dt><dd>' + score(r.total) + '</dd></div>' +
        '<div><dt>已保存检查记录</dt><dd>' + safePublicCount(r.agents) + ' 条</dd></div>' +
        '</dl></article>';
    }).join("") + '</div>';
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
    if (!rows.length) return '<p class="muted">尚无生成调用记录。</p>';
    const body = rows.map(function (call) {
      const prompt = Number(call.prompt_tokens) || 0;
      const response = Number(call.response_tokens) || 0;
      const duration = Number(call.duration_ms);
      return '<tr>' +
        '<td>' + escapeHtml(stepLabel(call.task || call.operation || "")) + '</td>' +
        '<td>' + statusBadge(call.status || "unknown") + '</td>' +
        '<td>' + (isFinite(duration) ? escapeHtml((duration / 1000).toFixed(1) + " 秒") : "—") + '</td>' +
        '<td>' + escapeHtml(String(prompt)) + ' / ' + escapeHtml(String(response)) + '</td>' +
        '<td>' + escapeHtml(String(call.attempt || 1)) + '</td>' +
        '</tr>';
    }).join("");
    return tableScroll('<table class="table table-wide"><thead><tr>' +
      '<th>任务</th><th>状态</th><th>耗时</th><th>输入 / 输出文字用量</th><th>尝试</th>' +
      '</tr></thead><tbody>' + body + '</tbody></table>');
  }
  async function initJobs() {
    bindCtaActions();
    ensureJobCancelDelegate();
    const recentBox = document.getElementById("jobs-recent");
    const logsBox = document.getElementById("jobs-logs");
    if (recentBox) recentBox.innerHTML = skeleton(4);
    if (logsBox) logsBox.innerHTML = "";
    try {
      const data = await fetchJson(wsUrl("/jobs/recent?n=20"));
      const items = Array.isArray(data.jobs) ? data.jobs : [];
      if (!items.length) {
        recentBox.innerHTML = emptyState("还没有任务记录", "从创作工作台开始一个阶段后，会在这里显示已保存进度。", '<a class="btn btn-primary" href="' + wsHref("/workbench") + '">进入创作工作台</a>');
      } else {
        const byId = new Map();
        const rows = items.map((job) => {
          byId.set(job.job_id || "", job);
          const status = String(job.status || "unknown").toLowerCase();
          const group = status === "running" || status === "pending" ? "active" : status === "succeeded" ? "done" : "attention";
          let action = "";
          if (group === "active") {
            action = '<button type="button" class="btn btn-secondary" data-cancel-job="' + escapeHtml(job.job_id || "") + '">请求取消</button>';
          } else if (status === "succeeded") {
            const chapter = jobChapterNumber(job);
            action = chapter
              ? '<a class="btn btn-primary" href="' + wsHref("/chapter/" + chapter) + '">打开章节</a>'
              : '<a class="btn btn-primary" href="' + wsHref("/workbench") + '">查看结果</a>';
          } else if (status === "lost" || !STATUS_LABELS[status]) {
            action = '<button type="button" class="btn btn-secondary" data-refresh-jobs>刷新状态</button>';
          } else if (jobActionKind(job) === "retry_exhausted") {
            action = renderJobPageCta("retry_exhausted", job);
          } else if (job.retryable === true) {
            const paid = isPaidNovelJobStep(job.step);
            action = '<button type="button" class="btn ' + (paid ? "btn-paid" : "btn-secondary") + '" data-job-retry="' + escapeHtml(job.job_id || "") + '"' + (paid ? ' data-ui-action="paid"' : '') + '>重新开始</button>';
          } else {
            action = renderJobPageCta(jobActionKind(job), job) || '<a class="btn btn-secondary" href="' + wsHref("/workbench") + '">返回工作台</a>';
          }
          return (
            '<article class="job-record-card" data-job-card data-job-group="' + group + '">' +
            '<div class="job-record-main"><p class="eyebrow ornament">任务</p><h2>' + escapeHtml(stepLabel(job.step)) + '</h2>' +
            '<p class="muted">最近更新：' + escapeHtml(formatJobTimestamp(job.finished_at || job.started_at)) + '</p></div>' +
            '<div class="job-record-state">' + statusBadge(status) +
            (group === "active" && Number.isFinite(Number(job.progress))
              ? '<p>当前进度：' + Math.max(0, Math.min(100, Math.round(Number(job.progress) * 100))) + '%</p>'
              : '<p>' + escapeHtml(jobActionableSummary(job)) + '</p>') + '</div>' +
            '<div class="job-record-action">' + action + '</div></article>'
          );
        }).join("");
        recentBox.innerHTML = '<div class="job-record-list">' + rows + '</div><div id="jobs-empty-filter" hidden></div>';
        recentBox.onclick = function (ev) {
          if (ev.target.closest("[data-refresh-jobs]")) { initJobs(); return; }
          const retry = ev.target.closest("[data-job-retry]");
          if (retry) {
            retryJob(byId.get(retry.getAttribute("data-job-retry") || ""), retry);
          }
        };
        bindJobFilters();
      }
    } catch (err) {
      recentBox.innerHTML = publicLoadError("任务状态没有读取成功", "已保存内容不受影响；不会自动重新开始任何任务。", '<button type="button" class="btn btn-secondary" data-refresh-jobs>刷新状态</button>');
      recentBox.onclick = function (ev) { if (ev.target.closest("[data-refresh-jobs]")) initJobs(); };
    }
  }
  function bindJobFilters() {
    const buttons = Array.from(document.querySelectorAll("[data-job-filter]"));
    const cards = Array.from(document.querySelectorAll("[data-job-card]"));
    const live = document.getElementById("jobs-filter-status");
    function apply(filter) {
      let shown = 0;
      cards.forEach(function (card) {
        const visible = filter === "all" || card.dataset.jobGroup === filter;
        card.hidden = !visible;
        if (visible) shown += 1;
      });
      buttons.forEach(function (button) {
        const active = button.dataset.jobFilter === filter;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
      const empty = document.getElementById("jobs-empty-filter");
      if (empty) {
        empty.hidden = shown !== 0;
        empty.innerHTML = shown ? "" : emptyState("当前筛选没有任务", "切换到其他分类，或刷新已保存状态。", '<button type="button" class="btn btn-secondary" data-job-filter="all">查看全部</button>');
      }
      if (live) live.textContent = "显示 " + shown + " 项任务。";
    }
    buttons.forEach(function (button) { button.addEventListener("click", function () { apply(button.dataset.jobFilter || "all"); }); });
    const recentBox = document.getElementById("jobs-recent");
    if (recentBox) recentBox.addEventListener("click", function (ev) {
      if (ev.target.closest("#jobs-empty-filter [data-job-filter]")) apply("all");
    });
    apply("all");
  }

  let accessibleControlSeq = 0;
  function associateFormLabels(root) {
    const scope = root && root.querySelectorAll ? root : document;
    const scoped = scope.matches && scope.matches(".ui-public, .ui-novel")
      ? scope
      : (scope.closest && scope.closest(".ui-public, .ui-novel"));
    if (!scoped && scope !== document) return;
    scope.querySelectorAll(".field > label").forEach(function (label) {
      const field = label.parentElement;
      const targetId = label.getAttribute("for");
      const control = targetId ? document.getElementById(targetId) : (field && field.querySelector("input, textarea, select"));
      if (!control) return;
      if (!control.id) control.id = "form-control-" + (++accessibleControlSeq);
      if (!targetId) label.setAttribute("for", control.id);
      if (control.required && !label.querySelector(".required-note")) {
        const note = document.createElement("span");
        note.className = "required-note";
        note.textContent = "（必填）";
        label.appendChild(note);
      }
    });
  }

  function observeAccessibleLabels() {
    const app = document.querySelector(".ui-public, .ui-novel");
    if (!app) return;
    associateFormLabels(app);
    const observer = new MutationObserver(function (records) {
      records.forEach(function (record) {
        record.addedNodes.forEach(function (node) {
          if (node.nodeType === 1) associateFormLabels(node);
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
    document.addEventListener("invalid", function (ev) {
        const control = ev.target;
        if (!control || !control.closest || !control.closest(".field")) return;
        control.setAttribute("aria-invalid", "true");
        const field = control.closest(".field");
        let error = field.querySelector(".field-error");
        if (!error) {
          error = document.createElement("small");
          error.className = "field-error";
          error.id = control.id + "-error";
          error.setAttribute("role", "alert");
          field.appendChild(error);
        }
        error.textContent = "请检查这一项后再继续。";
        const described = new Set((control.getAttribute("aria-describedby") || "").split(/\\s+/).filter(Boolean));
        described.add(error.id);
        control.setAttribute("aria-describedby", Array.from(described).join(" "));
    }, true);
    document.addEventListener("input", function (ev) {
        const control = ev.target;
        if (!control || !control.matches || !control.matches(".field input, .field textarea, .field select")) return;
        if (control.checkValidity()) {
          control.removeAttribute("aria-invalid");
          const field = control.closest(".field");
          const error = field && field.querySelector(".field-error");
          if (error) error.textContent = "";
        }
    });
  }

  // ---- dispatch ---------------------------------------------------------
  function boot() {
    initShellControls();
    observeAccessibleLabels();
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
  const panelPremise = document.getElementById("panel-premise");
  const panelProgress = document.getElementById("panel-progress");
  const typeForm = document.getElementById("type-form");
  const novelForm = document.getElementById("wizard-form");
  const premiseForm = document.getElementById("premise-form");
  const errBox = document.getElementById("upload-error");
  const premiseErrBox = document.getElementById("premise-error");
  const progressBody = document.getElementById("progress-body");
  const modeCard = document.getElementById("wizard-mode-card");
  const cancelRequestedJobs = new Set();
  const CTA_ACTIONS = {
    running: {
      title: "任务处理中",
      hint: "可以离开此页继续浏览；取消会在当前步骤完成后生效。",
    },
    succeeded: {
      title: "导入完成",
      hint: "下一步可以设置起点、查看章节，或进入续写入口。",
    },
    failed: {
      title: "任务未完成",
      hint: "当前输入已保留。查看任务说明后，可以回到创建向导重新开始。",
    },
    aborted: {
      title: "任务已取消",
      hint: "取消请求已生效；可以重新开始或返回书架。",
    },
  };
  const WIZARD_STATUS_LABELS = {
    pending: "等待中", running: "处理中", succeeded: "已完成",
    blocked: "需要补充", failed: "未完成", aborted: "已取消",
    cancelled: "已取消", canceled: "已取消", budget_exceeded: "额度不足",
    stale: "内容已更新", lost: "状态待确认",
  };
  function wizardStatusLabel(status) {
    return WIZARD_STATUS_LABELS[String(status || "").toLowerCase()] || "状态待确认";
  }
  function wizardSetBusy(control, busy, label) {
    if (!control) return;
    if (busy) {
      if (control.getAttribute("aria-busy") !== "true") {
        control.dataset.uiIdleLabel = control.textContent.trim();
        control.dataset.uiWasDisabled = control.disabled ? "1" : "0";
      }
      control.disabled = true;
      control.setAttribute("aria-busy", "true");
      if (label) control.textContent = label;
    } else {
      control.disabled = control.dataset.uiWasDisabled === "1";
      control.removeAttribute("aria-busy");
      if (control.dataset.uiIdleLabel) control.textContent = control.dataset.uiIdleLabel;
      delete control.dataset.uiIdleLabel;
      delete control.dataset.uiWasDisabled;
    }
  }
  function wizardSetFormBusy(form, busy, label) {
    if (!form) return;
    form.setAttribute("aria-busy", busy ? "true" : "false");
    form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (control) {
      wizardSetBusy(control, busy, label);
    });
  }

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
      card = { title: "操作没有完成", cause: "当前输入已保留。请检查页面提示后重试。" };
    }
    return '<div class="error-card" role="alert">' +
      '<div class="error-card-head"><span class="error-card-icon" aria-hidden="true">⚠</span>' +
      '<div class="error-card-copy"><p class="error-card-title">' + escapeHtml(card.title || "出错了") + '</p>' +
      '<p class="error-card-cause">' + escapeHtml(card.cause || "") + '</p></div></div>' +
      (card.trace_id ? '<p class="error-card-trace">编号 <code>' + escapeHtml(card.trace_id) + '</code></p>' : '') +
      "</div>";
  }

  loadServerMode();

  // Deep-link to the supported novel creation panels.
  (function applyTypeFromQuery() {
    var t = new URLSearchParams(location.search || "").get("type");
    if (!t) return;
    if (t === "premise") {
      if (typeForm) { try { typeForm.elements.ws_type.value = "premise"; } catch (e) {} }
      show(panelPremise);
    } else if (t === "novel") {
      show(panelUpload);
    }
  })();

  function show(panel) {
    [panelType, panelUpload, panelPremise, panelProgress].forEach((p) => {
      if (p) p.hidden = (p !== panel);
    });
  }

  async function loadServerMode() {
    if (!modeCard) return;
    try {
      const res = await fetch("/api/preflight");
      const data = await res.json().catch(() => ({}));
      if (!res.ok || typeof data.is_mock !== "boolean") throw new Error("mode_unavailable");
      const isMock = !!data.is_mock;
      const pricingKnown = data.pricing_known !== false;
      modeCard.innerHTML = '<strong>当前运行方式：' + (isMock ? "离线模式" : pricingKnown ? "真实生成" : "真实生成暂不可用") + '</strong>' +
        '<br><span class="muted">' +
        (isMock
          ? "本次不会发送真实请求，也不会使用真实额度。"
          : pricingKnown
            ? "开始前请确认本次范围与人民币额度。"
            : "当前模型缺少可信单价，系统会在首次真实请求前安全阻断；请先到设置中更换模型。") + "</span>";
    } catch (err) {
      modeCard.innerHTML = '<strong>当前运行方式：暂时无法确认</strong>' +
        '<br><span class="muted">没有开始创建，也不会自动发起请求。请重新加载页面后再试。</span>';
    }
  }

  if (typeForm) {
    typeForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      const t = typeForm.elements.ws_type.value;
      if (t === "premise") show(panelPremise);
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
          headers: {
            "Content-Type": "application/json",
            "X-Workspace-Mutation-Intent": "mutate-v1",
          },
          body: JSON.stringify({}),
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
      wizardSetFormBusy(novelForm, true, "正在导入并整理");
      try {
        const res = await fetch("/api/wizard/start", {
          method: "POST",
          headers: { "X-Onboarding-Intent": "import-v1" },
          body: fd,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          errBox.innerHTML = renderErrorCard(data);
          wizardSetFormBusy(novelForm, false);
          return;
        }
        show(panelProgress);
        poll(data.name, data.job_id);
      } catch (err) {
        err.code = err.code || "network";
        errBox.innerHTML = renderErrorCard(err);
        wizardSetFormBusy(novelForm, false);
      }
    });
  }

  if (premiseForm) {
    const premiseExpand = premiseForm.elements.expand;
    const premiseSubmit = premiseForm.querySelector("button[type=submit]");
    function syncPremiseSubmitKind() {
      const paid = !premiseExpand || premiseExpand.checked;
      premiseSubmit.classList.toggle("btn-paid", paid);
      premiseSubmit.classList.toggle("btn-primary", !paid);
      if (paid) premiseSubmit.setAttribute("data-ui-action", "paid");
      else premiseSubmit.removeAttribute("data-ui-action");
    }
    if (premiseExpand) premiseExpand.addEventListener("change", syncPremiseSubmitKind);
    syncPremiseSubmitKind();
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
      if (payload.expand && !await window.uiConfirmPaidAction({
        title: "确认从立意创建作品",
        action: "将根据当前立意生成作品设定。",
        scope: payload.expand ? "生成结构化立意扩写稿；最多 2 次模型请求；额度上限 1 元；最长等待 15 分钟" : "仅创建作品并保存立意",
        preservation: "当前输入会保留；开始后可在工作台查看和编辑结果。",
      })) return;
      wizardSetFormBusy(premiseForm, true, "正在创建原创故事");
      try {
        const res = await fetch("/api/wizard/premise-start", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Onboarding-Intent": "premise-v1",
          },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          if (premiseErrBox) premiseErrBox.innerHTML = renderErrorCard(data);
          wizardSetFormBusy(premiseForm, false);
          return;
        }
        window.setPendingToastAndNavigate(
          { kind: "info", msg: "已创建：" + data.name + "，进入工作台" },
          "/w/" + encodeURIComponent(data.name) + "/workbench"
        );
      } catch (err) {
        err.code = err.code || "network";
        if (premiseErrBox) premiseErrBox.innerHTML = renderErrorCard(err);
        wizardSetFormBusy(premiseForm, false);
      }
    });
  }


  async function poll(name, jobId) {
    while (true) {
      try {
        const res = await fetch("/api/workspace/" + encodeURIComponent(name) + "/job/" + jobId);
        const job = await res.json().catch(() => null);
        if (!res.ok || !job || typeof job !== "object") {
          renderWizardReconcile(name);
          wizardSetFormBusy(novelForm, false);
          return;
        }
        const disposition = wizardJobPollDisposition(job.status);
        if (disposition === "invalid") {
          renderWizardReconcile(name);
          wizardSetFormBusy(novelForm, false);
          return;
        }
        renderProgress(job, name, jobId);
        if (disposition === "terminal") {
          wizardSetFormBusy(novelForm, false);
          return;
        }
      } catch (err) {
        renderWizardReconcile(name);
        wizardSetFormBusy(novelForm, false);
        return;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  function wizardJobPollDisposition(status) {
    if (status === "pending" || status === "running") return "active";
    if (["succeeded", "blocked", "failed", "aborted", "lost", "budget_exceeded"].indexOf(status) >= 0) return "terminal";
    return "invalid";
  }
  function renderWizardReconcile(name) {
    const jobsHref = "/w/" + encodeURIComponent(name) + "/jobs";
    progressBody.innerHTML = '<div class="alert warn">任务状态无法确认，已停止自动刷新。请刷新或前往任务页核对。</div>' +
      '<div class="cluster"><a class="btn btn-secondary" href="' + jobsHref + '">查看任务页</a>' +
      '<a class="btn btn-ghost" href="">刷新页面</a></div>';
  }
  function renderProgress(job, name, jobId) {
    const pct = Math.round((job.progress || 0) * 100);
    progressBody.innerHTML =
      '<div class="kv-list compact">' +
      '<div class="k">状态</div><div class="v">' + escapeHtml(wizardStatusLabel(job.status)) + "</div>" +
      '<div class="k">当前步骤</div><div class="v">任务处理中</div>' +
      '<div class="k">进度</div><div class="v">' + pct + "%</div>" +
      '<div class="k">任务编号</div><div class="v"><code>' + escapeHtml(job.job_id) + "</code></div>" +
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
    const err = job.error ? '<div class="alert error">任务没有完成；当前输入和已生成内容会保留。请查看任务记录后重试。</div>' : "";
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
        '<a class="btn btn-primary" href="/wizard">回到创建向导重试</a>';
    }
    return '<div class="wizard-progress-actions">' +
      '<div class="alert ' + (group === "failed" ? "error" : group === "aborted" ? "warn" : "info") + '">' +
      '<strong>' + escapeHtml(cfg.title) + '</strong><br>' + escapeHtml(cfg.hint) + "</div>" +
      '<div id="cancel-notice">' +
      (cancelRequestedJobs.has(jobId) && group === "running" ? '<div class="alert info">取消请求已发送，等待当前步骤结束。</div>' : "") +
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
  const modeBox = document.getElementById("settings-mode");
  const submit = document.querySelector('button[form="settings-form"]');
  if (!form) return;
  let initial = {};
  let configured = {};
  const uiInitial = {};
  const editable = [
    { key: "OPENAI_STREAM", label: "逐步显示生成内容", help: "开启后，生成中的文字会逐步显示。", kind: "checkbox", group: "basic" },
    { key: "DISABLE_PROMPT_CACHE", label: "每次重新准备上下文", help: "开启后不复用已准备的上下文，通常会增加等待时间。", kind: "checkbox", group: "basic" },
    { key: "WRITE_MAX_TOKENS", label: "单章文字量上限", help: "留空时使用项目默认值；只填写正整数。", kind: "number", group: "basic" },
    { key: "WRITE_PROMPT_PROFILE", label: "正文写作方案", help: "留空时使用项目默认方案。", kind: "text", group: "advanced" },
    { key: "OPENAI_MODEL", label: "默认文字生成服务", help: "填写服务要求的完整标识。", kind: "text", group: "advanced" },
    { key: "OPENAI_BASE_URL", label: "默认文字生成地址", help: "仅在所用服务要求自定义地址时填写。", kind: "text", group: "advanced" },
    { key: "OPENAI_API_KEY", label: "默认文字生成凭据", help: "页面不会回显已保存内容；留空保持不变。", kind: "secret", group: "advanced" },
    { key: "MODEL_PROFILE", label: "生成配置方案", help: "留空时沿用项目默认方案。", kind: "text", group: "advanced" },
    { key: "PLANNER_MODEL", label: "故事规划生成服务", help: "留空时沿用默认文字生成服务。", kind: "text", group: "advanced" },
    { key: "PLANNER_BASE_URL", label: "故事规划生成地址", help: "仅在规划服务使用独立地址时填写。", kind: "text", group: "advanced" },
    { key: "PLANNER_API_KEY", label: "故事规划生成凭据", help: "页面不会回显已保存内容；留空保持不变。", kind: "secret", group: "advanced" },
  ];
  try {
    const responses = await Promise.all([fetch("/api/settings"), fetch("/api/preflight")]);
    const settingsData = await responses[0].json().catch(() => ({}));
    const modeData = await responses[1].json().catch(() => ({}));
    if (!responses[0].ok || !responses[1].ok || typeof modeData.is_mock !== "boolean") throw new Error("load_failed");
    initial = settingsData.settings && typeof settingsData.settings === "object" ? settingsData.settings : {};
    configured = settingsData.configured && typeof settingsData.configured === "object" ? settingsData.configured : {};
    if (modeBox) {
      modeBox.innerHTML = modeData.is_mock
        ? '<strong>离线模式</strong><span>当前不会发起真实生成请求，也不会使用真实额度。</span>'
        : modeData.pricing_known === false
          ? '<strong>真实生成暂不可用</strong><span>当前模型缺少可信单价，付费请求会被安全阻断。请更换为已有明确本地价格的模型并重启服务。</span>'
          : '<strong>真实生成方式已选择</strong><span>这不代表已经授权；每次使用前仍需确认范围与人民币额度。</span>';
    }
  } catch (err) {
    if (modeBox) modeBox.innerHTML = '<strong>运行方式未能读取</strong><span>没有修改任何设置。请重新加载页面后再试。</span>';
    errBox.innerHTML = '<div class="alert error">设置没有读取成功；已有设置没有改变。</div>' +
      '<button type="button" class="btn btn-secondary" data-cta-action="reload">重新加载</button>';
    if (submit) submit.disabled = true;
    return;
  }
  const advanced = document.createElement("details");
  advanced.className = "details-fold settings-advanced";
  advanced.innerHTML = '<summary>连接设置（高级）</summary><p class="muted">仅在需要连接你自己的生成服务时修改；保存不代表已经授权使用。</p><div class="stack" data-settings-advanced></div>';
  const advancedBody = advanced.querySelector("[data-settings-advanced]");
  editable.forEach(function (spec) {
    const v = typeof initial[spec.key] === "string" ? initial[spec.key] : "";
    const row = document.createElement("div");
    row.className = "field";
    const helpId = "setting-help-" + spec.key.toLowerCase().replace(/[^a-z0-9]+/g, "-");
    const inputId = "setting-" + spec.key.toLowerCase().replace(/[^a-z0-9]+/g, "-");
    if (spec.kind === "checkbox") {
      const checked = /^(?:1|true|yes|on)$/i.test(v);
      uiInitial[spec.key] = checked ? "1" : "0";
      row.innerHTML = '<label class="field-check" for="' + inputId + '">' +
        '<input id="' + inputId + '" name="' + spec.key + '" type="checkbox" value="1"' + (checked ? " checked" : "") +
        ' aria-describedby="' + helpId + '"> <span>' + escapeHtml(spec.label) + '</span></label>' +
        '<small id="' + helpId + '">' + escapeHtml(spec.help) + '</small>';
    } else if (spec.kind === "number") {
      const safeValue = /^\\d*$/.test(v) ? v : "";
      uiInitial[spec.key] = safeValue;
      row.innerHTML = '<label for="' + inputId + '">' + escapeHtml(spec.label) + '</label>' +
        '<input id="' + inputId + '" name="' + spec.key + '" type="number" min="1" step="1" value="' +
        escapeHtml(safeValue) + '" inputmode="numeric" aria-describedby="' + helpId + '">' +
        '<small id="' + helpId + '">' + escapeHtml(spec.help) + '</small>';
    } else {
      const secret = spec.kind === "secret";
      const safeValue = secret ? "" : v;
      uiInitial[spec.key] = safeValue;
      const configuredText = secret && configured[spec.key] ? "已配置；留空保持不变。" : spec.help;
      row.innerHTML = '<label for="' + inputId + '">' + escapeHtml(spec.label) + '</label>' +
        '<input id="' + inputId + '" name="' + spec.key + '" type="' + (secret ? "password" : "text") +
        '" value="' + escapeHtml(safeValue) + '" autocomplete="off" aria-describedby="' + helpId + '">' +
        '<small id="' + helpId + '">' + escapeHtml(configuredText) + '</small>';
    }
    (spec.group === "advanced" ? advancedBody : form).appendChild(row);
  });
  form.appendChild(advanced);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    errBox.innerHTML = "";
    if (banner) banner.hidden = true;
    const payload = {};
    for (const input of form.querySelectorAll("input")) {
      const value = input.type === "checkbox" ? (input.checked ? "1" : "0") : input.value.trim();
      if (value === uiInitial[input.name]) continue;
      payload[input.name] = value;
    }
    if (Object.keys(payload).length === 0) {
      errBox.innerHTML = '<div class="alert info">没有需要保存的修改。</div>';
      return;
    }
    form.setAttribute("aria-busy", "true");
    if (submit) { submit.disabled = true; submit.setAttribute("aria-busy", "true"); submit.textContent = "正在保存"; }
    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "X-Settings-Mutation-Intent": "update-v1",
        },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        errBox.innerHTML = '<div class="alert error">设置没有保存；当前输入已保留。请检查填写内容后重试。</div>';
        return;
      }
      Object.keys(payload).forEach(function (key) {
        const spec = editable.find(function (item) { return item.key === key; });
        const input = form.querySelector('[name="' + key + '"]');
        if (spec && spec.kind === "secret") {
          if (input) input.value = "";
          uiInitial[key] = "";
        } else {
          uiInitial[key] = payload[key];
        }
      });
      if (banner) {
        banner.hidden = false;
        banner.innerHTML = '<div class="alert info">设置已保存。请重启本地服务，让新设置生效。</div>';
      }
    } catch (err) {
      errBox.innerHTML = '<div class="alert error">设置没有保存；当前输入已保留。请确认本地服务仍在运行后重试。</div>';
    } finally {
      form.setAttribute("aria-busy", "false");
      if (submit) { submit.disabled = false; submit.removeAttribute("aria-busy"); submit.textContent = "保存设置"; }
    }
  });
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }
})();
"""
