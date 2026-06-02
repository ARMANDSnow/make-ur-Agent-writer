"""iter 025: embedded CSS and JS strings served by /static/*.

Keeping these as Python string constants means no separate static-file
handling layer is needed and the WebUI ships as a single Python package
import — no broken paths if the repo is moved.
"""

from __future__ import annotations


CSS_BODY = """\
* { box-sizing: border-box; }
:root {
  --bg: #f6f7f9;
  --panel: #ffffff;
  --line: #d9dee7;
  --line-strong: #b8c0cc;
  --text: #1c2430;
  --muted: #667085;
  --blue: #2563eb;
  --blue-soft: #e8f0ff;
  --green: #157347;
  --green-soft: #e8f7ee;
  --red: #b42318;
  --red-soft: #fdecec;
  --amber: #a15c07;
  --amber-soft: #fff4df;
  --violet: #6941c6;
  --violet-soft: #f1ecff;
}
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.55 -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif;
}
a { color: var(--blue); text-decoration: none; }
a:hover { text-decoration: underline; }
.app-header {
  min-height: 76px;
  padding: 18px 28px;
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: center;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
}
.app-header h1 { margin: 0; font-size: 22px; font-weight: 700; }
.app-header h1 a { margin-right: 8px; }
.app-header nav { display: flex; gap: 10px; flex-wrap: wrap; }
.muted { color: var(--muted); }
.app-header .muted { margin: 4px 0 0; font-size: 12px; }
.page-shell {
  width: min(1320px, calc(100vw - 48px));
  margin: 0 auto;
  padding: 20px 0 40px;
}
.hero-band, .workspace-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  padding: 18px 0 20px;
  border-bottom: 1px solid var(--line);
}
.hero-band h2, .workspace-hero h2 { margin: 2px 0 0; font-size: 24px; line-height: 1.25; }
.eyebrow { margin: 0; color: var(--violet); font-size: 12px; font-weight: 700; text-transform: uppercase; }
.hero-stats, .summary-strip { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.stat, .pill {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 4px 9px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--panel);
  color: var(--muted);
  font-size: 12px;
  font-weight: 650;
}
.pill.ready, .status-ready { color: var(--green); background: var(--green-soft); border-color: #b7e2c8; }
.pill.warn, .status-warn { color: var(--amber); background: var(--amber-soft); border-color: #f1ce94; }
.pill.blocked, .status-blocked { color: var(--red); background: var(--red-soft); border-color: #f5b5b0; }
.section-flat { padding-top: 18px; }
.workspace-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
.workspace-card {
  display: block;
  min-height: 184px;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--text);
}
.workspace-card:hover { border-color: var(--line-strong); text-decoration: none; }
.workspace-card h3 { margin: 0 0 12px; font-size: 18px; }
.workspace-card .meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.metric { padding: 8px; border: 1px solid var(--line); border-radius: 6px; background: #fafbfc; }
.metric .k { display: block; color: var(--muted); font-size: 11px; }
.metric .v { display: block; margin-top: 2px; font-size: 15px; font-weight: 700; }
.cockpit-grid { margin-top: 18px; display: grid; grid-template-columns: minmax(420px, 1.1fr) minmax(360px, 0.9fr); gap: 14px; }
.panel, .tabs {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
}
.panel { padding: 16px; }
.panel-title { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; }
.panel-title h2 { margin: 0; font-size: 16px; }
.panel-body { font-size: 13px; }
.control-grid, .write-grid { display: grid; gap: 10px; margin-bottom: 14px; }
.control-grid { grid-template-columns: minmax(220px, 1fr) max-content; align-items: end; }
.write-grid { grid-template-columns: repeat(3, minmax(120px, 1fr)); }
label { display: grid; gap: 5px; color: var(--muted); font-size: 12px; font-weight: 650; }
input, select {
  width: 100%;
  min-height: 36px;
  padding: 7px 9px;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  background: #fff;
  color: var(--text);
  font: inherit;
}
input[type=checkbox] { width: auto; min-height: auto; }
.check-row { display: flex; align-items: center; gap: 8px; color: var(--text); }
.button, button {
  min-height: 36px;
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 7px 12px;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
  text-align: center;
}
.button.primary, button.primary { background: var(--blue); color: #fff; }
.button.secondary, button.secondary { background: var(--blue-soft); color: var(--blue); border-color: #bed3ff; }
button:disabled { opacity: 0.55; cursor: not-allowed; }
.icon-button {
  width: 34px;
  padding: 0;
  background: #fff;
  border-color: var(--line);
  color: var(--muted);
}
.tabs { margin-top: 14px; overflow: hidden; }
.tab-list { display: flex; gap: 0; border-bottom: 1px solid var(--line); background: #fbfcfe; overflow-x: auto; }
.tab {
  border: 0;
  border-right: 1px solid var(--line);
  border-radius: 0;
  background: transparent;
  color: var(--muted);
  white-space: nowrap;
}
.tab.active { background: var(--panel); color: var(--text); }
.tab-panel { display: none; padding: 14px; }
.tab-panel.active { display: block; }
.kv { display: grid; grid-template-columns: max-content 1fr; gap: 6px 12px; align-items: start; }
.kv .k { color: var(--muted); }
table.reviews, table.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
table.reviews th, table.reviews td, table.data-table th, table.data-table td { padding: 7px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
table.reviews tr.row-toggle, tr.draft-row { cursor: pointer; }
table.reviews tr.row-toggle:hover, tr.draft-row:hover { background: #f7f9fc; }
table.reviews td.verdict-approve { color: var(--green); font-weight: 700; }
table.reviews td.verdict-reject { color: var(--red); font-weight: 700; }
table.reviews td.verdict-abstain { color: var(--amber); font-weight: 700; }
.review-detail, .draft-preview {
  background: #fbfcfe;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 12px;
}
pre, code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.review-detail pre, .draft-preview pre {
  white-space: pre-wrap;
  word-break: break-word;
  margin: 8px 0 0;
  color: var(--text);
}
.error { color: var(--red); }
.warn-text { color: var(--amber); }
.command-list code {
  display: block;
  margin: 6px 0;
  padding: 7px 9px;
  background: #fbfcfe;
  border: 1px solid var(--line);
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
}
.progress-bar { margin-top: 10px; height: 9px; background: #edf1f7; border-radius: 99px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--blue); transition: width 0.25s ease; }
@media (max-width: 960px) {
  .app-header, .hero-band, .workspace-hero { align-items: flex-start; flex-direction: column; }
  .page-shell { width: min(100vw - 28px, 1320px); }
  .cockpit-grid, .write-grid, .control-grid { grid-template-columns: 1fr; }
}
"""


JS_SETTINGS = """\
(async function () {
  const form = document.getElementById('settings-form');
  const errBox = document.getElementById('settings-error');
  const banner = document.getElementById('restart-banner');
  if (!form) return;

  let initial = {};
  try {
    const res = await fetch('/api/settings');
    const data = await res.json();
    initial = data.settings || {};
  } catch (err) {
    errBox.textContent = `读取失败: ${err}`;
    return;
  }
  for (const [k, v] of Object.entries(initial)) {
    const row = document.createElement('div');
    row.className = 'kv-row';
    row.innerHTML = `<label><span class="k">${escapeHtml(k)}</span>` +
      `<input name="${escapeHtml(k)}" type="text" value="${escapeHtml(v)}" placeholder="(empty)" autocomplete="off"></label>`;
    form.appendChild(row);
  }
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    errBox.textContent = '';
    banner.hidden = true;
    const payload = {};
    for (const input of form.querySelectorAll('input')) {
      // Skip masked API key fields the user didn't actually edit
      // (they'd otherwise overwrite the real key with a masked placeholder).
      if (input.value === initial[input.name]) continue;
      payload[input.name] = input.value;
    }
    if (Object.keys(payload).length === 0) {
      errBox.textContent = '(没有改动)';
      return;
    }
    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        errBox.textContent = `保存失败 (${res.status}): ${data.error || ''}`;
        return;
      }
      banner.hidden = false;
      banner.textContent = `已保存 ${data.updated_keys?.join(', ') || ''}，请重启 web 服务以使新模型生效`;
    } catch (err) {
      errBox.textContent = `网络错误: ${err}`;
    }
  });
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
})();
"""


JS_WIZARD = """\
(function () {
  const form = document.getElementById('wizard-form');
  const errBox = document.getElementById('upload-error');
  const progressPanel = document.getElementById('panel-progress');
  const progressBody = document.getElementById('progress-body');
  if (!form) return;

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    errBox.textContent = '';
    const fd = new FormData(form);
    const submitBtn = form.querySelector('button[type=submit]');
    submitBtn.disabled = true;
    try {
      const res = await fetch('/api/wizard/start', { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) {
        errBox.textContent = `上传失败 (${res.status}): ${data.error || ''}`;
        submitBtn.disabled = false;
        return;
      }
      progressPanel.hidden = false;
      poll(data.name, data.job_id);
    } catch (err) {
      errBox.textContent = `网络错误: ${err}`;
      submitBtn.disabled = false;
    }
  });

  async function poll(name, jobId) {
    while (true) {
      try {
        const res = await fetch(`/api/workspace/${encodeURIComponent(name)}/job/${jobId}`);
        const job = await res.json();
        renderProgress(job);
        if (job.status === 'succeeded') {
          progressBody.innerHTML += `<p><a href="/workspace/${encodeURIComponent(name)}/">→ 进入 dashboard</a></p>`;
          return;
        }
        if (['blocked', 'failed', 'aborted', 'lost'].includes(job.status)) {
          progressBody.innerHTML += `<p class="error">失败: ${escapeHtml(job.error || '')} (trace_id=${job.trace_id || '?'})</p>`;
          return;
        }
      } catch (err) {
        progressBody.innerHTML = `<p class="error">轮询失败: ${err}</p>`;
        return;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
  }

  function renderProgress(job) {
    const pct = Math.round((job.progress || 0) * 100);
    progressBody.innerHTML = `
      <div class="kv">
        <div class="k">status</div><div>${escapeHtml(job.status)}</div>
        <div class="k">current step</div><div>${escapeHtml(job.current_step || '?')}</div>
        <div class="k">progress</div><div>${pct}%</div>
        <div class="k">job_id</div><div><code>${escapeHtml(job.job_id)}</code></div>
      </div>
      <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
})();
"""


JS_DASHBOARD = """\
(async function () {
  if (window.PAGE_KIND === 'index') {
    initIndex();
    return;
  }
  if (window.PAGE_KIND === 'workspace') {
    initWorkspace();
  }

  async function initIndex() {
    const shelf = document.getElementById('workspace-shelf');
    const stats = document.getElementById('shelf-stats');
    if (!shelf) return;
    try {
      const data = await fetchJson('/api/workspaces/overview');
      const workspaces = data.workspaces || [];
      if (!workspaces.length) {
        shelf.innerHTML = `<p class="muted">${escapeHtml(shelf.dataset.empty || '(empty)')}</p>`;
        stats.innerHTML = '';
        return;
      }
      const ready = workspaces.filter((w) => w.readiness?.status === 'ready').length;
      const warn = workspaces.filter((w) => w.readiness?.status === 'warn').length;
      const blocked = workspaces.filter((w) => w.readiness?.status === 'blocked').length;
      stats.innerHTML = [
        `<span class="stat">作品 ${workspaces.length}</span>`,
        `<span class="stat status-ready">ready ${ready}</span>`,
        `<span class="stat status-warn">warn ${warn}</span>`,
        `<span class="stat status-blocked">blocked ${blocked}</span>`,
      ].join('');
      shelf.innerHTML = workspaces.map(renderWorkspaceCard).join('');
    } catch (err) {
      shelf.innerHTML = `<p class="error">加载失败: ${escapeHtml(err)}</p>`;
    }
  }

  function renderWorkspaceCard(w) {
    const readiness = w.readiness || {};
    const status = readiness.status || 'blocked';
    const blockers = readiness.blockers || [];
    const recent = w.recent_job ? `${w.recent_job.step || '?'} / ${w.recent_job.status || '?'}` : '无';
    const start = w.start_point?.has_start_point ? (w.start_point.start_chapter_id || '已设置') : '未设置';
    const plan = w.plan?.exists ? `${w.plan.chapters || 0} 章` : '缺失';
    return `
      <a class="workspace-card" href="/workspace/${encodeURIComponent(w.name)}/">
        <div class="panel-title">
          <h3>${escapeHtml(w.name)}</h3>
          <span class="pill ${escapeHtml(status)}">${escapeHtml(status)}</span>
        </div>
        <div class="meta-grid">
          <span class="metric"><span class="k">原文章节</span><span class="v">${escapeHtml(w.chapter_count || 0)}</span></span>
          <span class="metric"><span class="k">续写草稿</span><span class="v">${escapeHtml(w.draft_count || 0)}</span></span>
          <span class="metric"><span class="k">起点</span><span class="v">${escapeHtml(start)}</span></span>
          <span class="metric"><span class="k">计划</span><span class="v">${escapeHtml(plan)}</span></span>
          <span class="metric"><span class="k">评审通过</span><span class="v">${escapeHtml(w.review_accepted || 0)} / ${escapeHtml(w.review_total || 0)}</span></span>
          <span class="metric"><span class="k">最近任务</span><span class="v">${escapeHtml(recent)}</span></span>
        </div>
        ${blockers.length ? `<p class="error">${escapeHtml(blockers[0])}</p>` : ''}
      </a>`;
  }

  async function initWorkspace() {
  const ws = window.WORKSPACE_NAME;
  if (!ws) return;
    bindTabs();
    await loadWorkspaceShell();
    await loadSecondaryPanels();
    bindStartPoint();
    bindPlan();
    bindWriteBook();
    document.getElementById('refresh-readiness')?.addEventListener('click', refreshReadiness);
  }

  async function loadWorkspaceShell() {
    const overview = await fetchJson('/api/workspaces/overview');
    const item = (overview.workspaces || []).find((w) => w.name === window.WORKSPACE_NAME);
    renderWorkspaceSummary(item || {});
    await populateStartPointSelect();
    await refreshReadiness();
    await refreshRecentJobs();
    await loadDrafts();
  }

  function renderWorkspaceSummary(item) {
    const box = document.getElementById('workspace-summary');
    if (!box) return;
    const readiness = item.readiness?.status || 'blocked';
    box.innerHTML = [
      `<span class="pill ${escapeHtml(readiness)}">${escapeHtml(readiness)}</span>`,
      `<span class="stat">原文章节 ${escapeHtml(item.chapter_count || 0)}</span>`,
      `<span class="stat">草稿 ${escapeHtml(item.draft_count || 0)}</span>`,
      `<span class="stat">计划 ${escapeHtml(item.plan?.chapters || 0)} 章</span>`,
      `<span class="stat">评审 ${escapeHtml(item.review_accepted || 0)} / ${escapeHtml(item.review_total || 0)}</span>`,
    ].join('');
  }

  async function loadSecondaryPanels() {
  const panels = document.querySelectorAll('.panel-body[data-source]');
  for (const panel of panels) {
    const source = panel.dataset.source;
    try {
      const res = await fetch(sourceUrl(source));
      const data = await res.json();
      panel.innerHTML = render(source, data);
    } catch (err) {
      panel.innerHTML = `<span class="error">load failed: ${err}</span>`;
    }
  }
  }

  function render(kind, data) {
    if (kind === 'status') return renderKV(data);
    if (kind === 'cost') return renderKV(data);
    if (kind === 'manifest') return renderManifest(data);
    if (kind === 'reviews') return renderReviews(data);
    return `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  }

  function sourceUrl(source) {
    return `/api/workspace/${encodeURIComponent(window.WORKSPACE_NAME)}/${source}`;
  }

  function renderKV(obj) {
    const rows = [];
    for (const [k, v] of Object.entries(obj || {})) {
      const val = typeof v === 'object' ? JSON.stringify(v) : String(v);
      rows.push(`<div class="k">${escapeHtml(k)}</div><div>${escapeHtml(val)}</div>`);
    }
    return rows.length ? `<div class="kv">${rows.join('')}</div>` : '<span class="muted">(empty)</span>';
  }

  function renderManifest(data) {
    const chs = (data && data.chapters) || [];
    if (!chs.length) return '<span class="muted">(no manifest)</span>';
    const head = '<tr><th>idx</th><th>chapter_id</th><th>title</th><th>chars</th></tr>';
    const rows = chs.slice(0, 200).map((c, i) => `<tr><td>${i + 1}</td><td>${escapeHtml(c.chapter_id || '')}</td><td>${escapeHtml(c.title || '')}</td><td>${escapeHtml(String(c.char_count ?? ''))}</td></tr>`).join('');
    const more = chs.length > 200 ? `<p class="muted">(${chs.length - 200} more rows hidden)</p>` : '';
    return `<table class="reviews">${head}${rows}</table>${more}`;
  }

  function renderReadiness(data) {
    const status = data.status || 'unknown';
    const blockers = data.blockers || [];
    const warnings = data.warnings || [];
    const commands = data.recommended_commands || [];
    const rows = [
      `<div class="k">status</div><div><span class="pill ${escapeHtml(status)}">${escapeHtml(status)}</span></div>`,
      `<div class="k">chapters</div><div>${escapeHtml(String(data.chapters || '?'))}</div>`,
      `<div class="k">resume_from</div><div>${escapeHtml(String(data.resume_from || '?'))}</div>`,
      `<div class="k">plan_window</div><div>${escapeHtml(String(data.plan_window || '?'))}</div>`,
    ];
    let html = `<div class="kv">${rows.join('')}</div>`;
    if (blockers.length) html += `<p class="error">${blockers.map(escapeHtml).join('<br>')}</p>`;
    if (warnings.length) html += `<p class="warn-text">${warnings.map(escapeHtml).join('<br>')}</p>`;
    if (commands.length) html += `<div class="command-list">${commands.map((c) => `<code>${escapeHtml(c)}</code>`).join('')}</div>`;
    return html;
  }

  function renderReviews(data) {
    const chs = (data && data.chapters) || [];
    const stats = (data && data.stats) || {};
    if (!chs.length) return '<span class="muted">(no reviews)</span>';
    const statsLine = `total=${stats.total} accepted=${stats.accepted} rewrite_max=${stats.rewrite_max} advisor=${stats.advisor_suggestions_total}`;
    const head = '<tr><th>ch</th><th>verdict</th><th>rewrite</th><th>chars</th><th>agents</th><th>advisor</th></tr>';
    const rows = chs.map((c) => {
      const verdictClass = c.verdict === 'Approve' ? 'verdict-approve' : c.verdict === 'Reject' ? 'verdict-reject' : 'verdict-abstain';
      const main = `<tr class="row-toggle" data-ch="${c.chapter}"><td>${c.chapter}</td><td class="${verdictClass}">${escapeHtml(c.verdict || '?')}</td><td>${c.rewrite_count}</td><td>${c.chinese_char_count}</td><td>${(c.agent_reviews || []).length}</td><td>${(c.rewrite_suggestions || []).length}</td></tr>`;
      const detail = `<tr class="review-detail-row" id="detail-${c.chapter}" hidden><td colspan="6"><div class="review-detail">${renderChapterDetail(c)}</div></td></tr>`;
      return main + detail;
    }).join('');
    return `<p class="muted">${statsLine}</p><table class="reviews">${head}${rows}</table>`;
  }

  function renderChapterDetail(c) {
    const blocks = [];
    if ((c.agent_reviews || []).length) {
      const agentRows = c.agent_reviews.map((a) => {
        const sub = a.sub_scores ? ` sub=${JSON.stringify(a.sub_scores)}` : '';
        return `<pre>${escapeHtml(a.agent_name)} · ${escapeHtml(a.verdict || '?')} · score=${a.score}${sub}\\nissues: ${escapeHtml(JSON.stringify(a.issues || []))}\\nsuggestions: ${escapeHtml(JSON.stringify(a.suggestions || []))}</pre>`;
      }).join('');
      blocks.push(`<strong>agent_reviews</strong>${agentRows}`);
    }
    if ((c.rewrite_suggestions || []).length) {
      const advRows = c.rewrite_suggestions.map((s) => `<pre>[${escapeHtml(s.type || '?')}] ${escapeHtml(s.section || '')}\\n${escapeHtml(s.guidance || '')}</pre>`).join('');
      blocks.push(`<strong>advisor rewrite_suggestions</strong>${advRows}`);
    }
    if ((c.lint_issues || []).length) {
      blocks.push(`<strong>lint_issues</strong><pre>${escapeHtml(JSON.stringify(c.lint_issues, null, 2))}</pre>`);
    }
    return blocks.length ? blocks.join('') : '<span class="muted">(no detail)</span>';
  }

  document.addEventListener('click', (e) => {
    const row = e.target.closest('tr.row-toggle');
    if (row) {
      const detail = document.getElementById(`detail-${row.dataset.ch}`);
      if (detail) detail.hidden = !detail.hidden;
      return;
    }
    const draft = e.target.closest('tr.draft-row');
    if (draft) {
      loadDraftPreview(draft.dataset.chapter);
    }
  });

  async function populateStartPointSelect() {
    const select = document.getElementById('start-point-select');
    if (!select) return;
    const [manifestData, startData] = await Promise.all([
      fetchJson(`/api/workspace/${encodeURIComponent(window.WORKSPACE_NAME)}/manifest`),
      fetchJson(`/api/workspace/${encodeURIComponent(window.WORKSPACE_NAME)}/start-point`),
    ]);
    const chapters = manifestData.chapters || [];
    const current = startData.start_point?.start_chapter_id || startData.start_point?.manifest?.volume_id || '';
    const byVolume = new Map();
    for (const ch of chapters) {
      const volume = ch.volume_id || 'unknown';
      if (!byVolume.has(volume)) byVolume.set(volume, []);
      byVolume.get(volume).push(ch);
    }
    let html = '<option value="">选择续写起点</option>';
    for (const [volume, entries] of byVolume.entries()) {
      html += `<optgroup label="${escapeHtml(volume)}">`;
      html += `<option value="${escapeHtml(volume)}">卷末: ${escapeHtml(volume)}</option>`;
      for (const ch of entries) {
        html += `<option value="${escapeHtml(ch.chapter_id || '')}">${escapeHtml(ch.chapter_id || '')} · ${escapeHtml(ch.title || '')}</option>`;
      }
      html += '</optgroup>';
    }
    select.innerHTML = html;
    if (current) select.value = current;
  }

  function bindStartPoint() {
    const form = document.getElementById('start-point-form');
    if (!form) return;
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const value = form.elements.start_point.value;
      const box = document.getElementById('job-status');
      if (!value) {
        box.innerHTML = '<p class="error">请选择一个起点</p>';
        return;
      }
      try {
        const data = await postJson(`/api/workspace/${encodeURIComponent(window.WORKSPACE_NAME)}/start-point`, { start_point: value });
        box.innerHTML = `<p class="muted">起点已保存: ${escapeHtml(data.start_point?.start_chapter_id || value)}</p>`;
        await refreshReadiness();
      } catch (err) {
        box.innerHTML = `<p class="error">保存失败: ${escapeHtml(err)}</p>`;
      }
    });
  }

  function bindPlan() {
    const form = document.getElementById('plan-form');
    const submit = document.getElementById('plan-submit');
    const box = document.getElementById('job-status');
    if (!form || !submit || !box) return;
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      submit.disabled = true;
      box.innerHTML = '<span class="muted">starting plan...</span>';
      try {
        const data = await postJson(`/api/workspace/${encodeURIComponent(window.WORKSPACE_NAME)}/run`, {
          step: 'plan-chapters',
          params: { target_chapters: Number(form.elements.target_chapters.value || 5) },
        });
        await pollJob(data.job_id, box, submit, async () => {
          await refreshReadiness();
          await loadWorkspaceShell();
        });
      } catch (err) {
        box.innerHTML = `<p class="error">${escapeHtml(err)}</p>`;
        submit.disabled = false;
      }
    });
  }

  function bindWriteBook() {
    const form = document.getElementById('write-book-form');
    const submit = document.getElementById('write-book-submit');
    const jobBox = document.getElementById('job-status');
    if (!form || !submit || !jobBox) return;
    form.addEventListener('input', refreshReadiness);
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      submit.disabled = true;
      jobBox.innerHTML = '<span class="muted">starting…</span>';
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
        const data = await postJson(`/api/workspace/${encodeURIComponent(window.WORKSPACE_NAME)}/run`, { step: 'write-book', params });
        await pollJob(data.job_id, jobBox, submit, async () => {
          await refreshReadiness();
          await refreshRecentJobs();
          await loadDrafts();
        });
      } catch (err) {
        jobBox.innerHTML = `<span class="error">network error: ${escapeHtml(err)}</span>`;
        submit.disabled = false;
      }
    });
  }

  async function refreshReadiness() {
    const form = document.getElementById('write-book-form');
    const panel = document.getElementById('readiness-panel');
    const pill = document.getElementById('readiness-pill');
    const submit = document.getElementById('write-book-submit');
    if (!form || !panel) return;
    const chapters = form.elements.chapters?.value || '1';
    const resumeFrom = form.elements.resume_from?.value || '1';
    const replanEvery = form.elements.replan_every?.value || '0';
    try {
      const data = await fetchJson(`/api/workspace/${encodeURIComponent(window.WORKSPACE_NAME)}/readiness?chapters=${encodeURIComponent(chapters)}&resume_from=${encodeURIComponent(resumeFrom)}&replan_every=${encodeURIComponent(replanEvery)}`);
      panel.innerHTML = renderReadiness(data);
      if (pill) {
        pill.className = `pill ${data.status || 'blocked'}`;
        pill.textContent = data.status || 'blocked';
      }
      if (submit) submit.disabled = data.status === 'blocked';
    } catch (err) {
      panel.innerHTML = `<span class="error">load failed: ${escapeHtml(err)}</span>`;
      if (submit) submit.disabled = true;
    }
  }

  async function refreshRecentJobs() {
    const box = document.getElementById('recent-jobs');
    if (!box) return;
    try {
      const data = await fetchJson(`/api/workspace/${encodeURIComponent(window.WORKSPACE_NAME)}/jobs/recent?n=3`);
      const jobs = data.jobs || [];
      if (!jobs.length) {
        box.innerHTML = '<p class="muted">最近任务: 无</p>';
        return;
      }
      box.innerHTML = '<h3>最近任务</h3>' + jobs.map((job) => `<div class="kv">
        <div class="k">step</div><div>${escapeHtml(job.step || '?')}</div>
        <div class="k">status</div><div>${escapeHtml(job.status || '?')}</div>
        <div class="k">job</div><div><code>${escapeHtml(job.job_id || '')}</code></div>
      </div>`).join('');
    } catch (err) {
      box.innerHTML = `<p class="error">最近任务读取失败: ${escapeHtml(err)}</p>`;
    }
  }

  async function pollJob(jobId, box, submit, refreshReadiness) {
    while (true) {
      const job = await fetchJson(`/api/workspace/${encodeURIComponent(window.WORKSPACE_NAME)}/job/${jobId}`);
      const pct = Math.round((job.progress || 0) * 100);
      box.innerHTML = `
        <div class="kv">
          <div class="k">job</div><div><code>${escapeHtml(jobId)}</code></div>
          <div class="k">status</div><div>${escapeHtml(job.status || '?')}</div>
          <div class="k">step</div><div>${escapeHtml(job.current_step || '?')}</div>
          <div class="k">progress</div><div>${pct}%</div>
        </div>
        <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
        ${renderJobSummary(job.result_summary)}
        ${job.error ? `<p class="error">${escapeHtml(job.error)}</p>` : ''}`;
      if (['succeeded', 'blocked', 'failed', 'aborted', 'lost', 'budget_exceeded'].includes(job.status)) {
        submit.disabled = false;
        await refreshReadiness();
        return;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
  }

  function renderJobSummary(summary) {
    if (!summary || typeof summary !== 'object') return '';
    const rows = [];
    for (const [k, v] of Object.entries(summary)) {
      if (v === undefined || v === null) continue;
      const val = typeof v === 'object' ? JSON.stringify(v) : String(v);
      rows.push(`<div class="k">${escapeHtml(k)}</div><div>${escapeHtml(val)}</div>`);
    }
    return rows.length ? `<div class="kv">${rows.join('')}</div>` : '';
  }

  async function loadDrafts() {
    const box = document.getElementById('drafts-panel');
    if (!box) return;
    try {
      const data = await fetchJson(`/api/workspace/${encodeURIComponent(window.WORKSPACE_NAME)}/drafts`);
      const drafts = data.drafts || [];
      if (!drafts.length) {
        box.innerHTML = '<p class="muted">暂无续写草稿</p>';
        return;
      }
      const rows = drafts.map((d) => `<tr class="draft-row" data-chapter="${escapeHtml(d.chapter)}">
        <td>${escapeHtml(d.chapter)}</td>
        <td>${escapeHtml(d.verdict || '?')}</td>
        <td>${escapeHtml(d.review_verdict || '?')}</td>
        <td>${escapeHtml(d.needs_human_review ? 'yes' : 'no')}</td>
        <td>${escapeHtml(d.chars || 0)}</td>
      </tr>`).join('');
      box.innerHTML = `<table class="data-table"><tr><th>章</th><th>meta</th><th>review</th><th>人工复核</th><th>字符</th></tr>${rows}</table><div id="draft-preview" class="draft-preview"></div>`;
    } catch (err) {
      box.innerHTML = `<p class="error">草稿读取失败: ${escapeHtml(err)}</p>`;
    }
  }

  async function loadDraftPreview(chapter) {
    const box = document.getElementById('draft-preview');
    if (!box) return;
    box.innerHTML = '<p class="muted">loading...</p>';
    try {
      const data = await fetchJson(`/api/workspace/${encodeURIComponent(window.WORKSPACE_NAME)}/draft/${encodeURIComponent(chapter)}`);
      box.innerHTML = `<div class="kv">
        <div class="k">chapter</div><div>${escapeHtml(data.chapter)}</div>
        <div class="k">verdict</div><div>${escapeHtml(data.meta?.verdict || '?')}</div>
        <div class="k">review</div><div>${escapeHtml(data.review?.verdict || '?')}</div>
        <div class="k">path</div><div><code>${escapeHtml(data.path || '')}</code></div>
      </div><pre>${escapeHtml(data.content || '')}</pre>`;
    } catch (err) {
      box.innerHTML = `<p class="error">预览失败: ${escapeHtml(err)}</p>`;
    }
  }

  function bindTabs() {
    document.addEventListener('click', (ev) => {
      const tab = ev.target.closest('.tab');
      if (!tab) return;
      for (const item of document.querySelectorAll('.tab')) item.classList.remove('active');
      for (const panel of document.querySelectorAll('.tab-panel')) panel.classList.remove('active');
      tab.classList.add('active');
      document.getElementById(`tab-${tab.dataset.tab}`)?.classList.add('active');
    });
  }

  async function fetchJson(url) {
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `${res.status}`);
    return data;
  }

  async function postJson(url, payload) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `${res.status}`);
    return data;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
})();
"""
