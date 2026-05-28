"""iter 025: embedded CSS and JS strings served by /static/*.

Keeping these as Python string constants means no separate static-file
handling layer is needed and the WebUI ships as a single Python package
import — no broken paths if the repo is moved.
"""

from __future__ import annotations


CSS_BODY = """\
* { box-sizing: border-box; }
body {
  margin: 0;
  background: #0f1115;
  color: #e6e6e6;
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif;
}
header {
  padding: 16px 24px;
  border-bottom: 1px solid #2a2d35;
  background: #161922;
}
header h1 { margin: 0; font-size: 20px; font-weight: 600; }
header h1 a { color: #7aa2f7; text-decoration: none; margin-right: 8px; }
header .muted { margin: 4px 0 0; font-size: 12px; color: #8c93a3; }
main { padding: 16px 24px; display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 800px) { main { grid-template-columns: 1fr; } }
section { background: #161922; border: 1px solid #2a2d35; border-radius: 6px; padding: 12px 16px; }
section h2 { margin: 0 0 8px; font-size: 14px; font-weight: 600; color: #c0caf5; text-transform: uppercase; letter-spacing: 0.05em; }
.workspace-list { list-style: none; padding: 0; margin: 0; }
.workspace-list li { padding: 8px 0; border-bottom: 1px solid #2a2d35; }
.workspace-list li:last-child { border-bottom: none; }
.workspace-list a { color: #7aa2f7; text-decoration: none; font-size: 16px; }
.workspace-list a:hover { text-decoration: underline; }
.muted { color: #8c93a3; }
.panel-body { font-size: 13px; }
.kv { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; }
.kv .k { color: #8c93a3; }
table.reviews { width: 100%; border-collapse: collapse; font-size: 12px; }
table.reviews th, table.reviews td { padding: 4px 6px; border-bottom: 1px solid #2a2d35; text-align: left; }
table.reviews tr.row-toggle { cursor: pointer; }
table.reviews tr.row-toggle:hover { background: #1c2030; }
table.reviews td.verdict-approve { color: #9ece6a; }
table.reviews td.verdict-reject { color: #f7768e; }
table.reviews td.verdict-abstain { color: #e0af68; }
.review-detail { background: #11141c; padding: 8px 12px; font-size: 12px; }
.review-detail pre { white-space: pre-wrap; word-break: break-word; margin: 4px 0; color: #c0caf5; }
.error { color: #f7768e; }
form p { margin: 8px 0; }
form input[type=text], form input[type=file], form input[name=workspace] { background: #11141c; color: #e6e6e6; border: 1px solid #2a2d35; padding: 6px 8px; border-radius: 4px; width: 260px; }
form button { background: #7aa2f7; color: #11141c; border: 0; padding: 8px 16px; border-radius: 4px; font-weight: 600; cursor: pointer; }
form button:disabled { opacity: 0.5; cursor: not-allowed; }
.progress-bar { margin-top: 12px; height: 10px; background: #11141c; border: 1px solid #2a2d35; border-radius: 4px; overflow: hidden; }
.progress-fill { height: 100%; background: #9ece6a; transition: width 0.3s ease; }
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
      // (they'd otherwise overwrite the real key with "sk-***xxxx").
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
        if (job.status === 'done') {
          progressBody.innerHTML += `<p><a href="/workspace/${encodeURIComponent(name)}/">→ 进入 dashboard</a></p>`;
          return;
        }
        if (job.status === 'error') {
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
  const ws = window.WORKSPACE_NAME;
  if (!ws) return;
  const panels = document.querySelectorAll('.panel-body');
  for (const panel of panels) {
    const source = panel.dataset.source;
    try {
      const res = await fetch(`/api/workspace/${encodeURIComponent(ws)}/${source}`);
      const data = await res.json();
      panel.innerHTML = render(source, data);
    } catch (err) {
      panel.innerHTML = `<span class="error">load failed: ${err}</span>`;
    }
  }

  function render(kind, data) {
    if (kind === 'status') return renderKV(data);
    if (kind === 'cost') return renderKV(data);
    if (kind === 'manifest') return renderManifest(data);
    if (kind === 'reviews') return renderReviews(data);
    return `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
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

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  document.addEventListener('click', (e) => {
    const row = e.target.closest('tr.row-toggle');
    if (!row) return;
    const detail = document.getElementById(`detail-${row.dataset.ch}`);
    if (detail) detail.hidden = !detail.hidden;
  });
})();
"""
