//  SUMMARY & STANDUP VIEW
// ══════════════════════════════════════════════════════════
async function renderSummary(el) {
  // Check model status for soft lock
  let modelReady = true;
  try {
    const status = await api('/api/status');
    if (status.model && status.model.status !== 'ready') modelReady = false;
  } catch {}

  const softLockHtml = !modelReady ? `
    <div class="summary-locked-notice">
      <div class="summary-locked-icon">📝</div>
      <div class="summary-locked-text">
        <strong>Daily Summary needs Gemma 4 to generate.</strong><br>
        <a href="#" onclick="openModelHub();return false" style="color:var(--accent)">Open Model Hub</a> to download a model.
        Cached summaries from previous sessions are still shown below.
      </div>
    </div>` : '';

  el.innerHTML = `
    ${softLockHtml}
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:24px">
      <input type="date" id="summary-date" value="${currentDate}" max="${localToday()}">
      <span class="hint-trigger" id="summary-hint-trigger" style="display:none" title="">?</span>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
      <div class="card">
        <div class="card-header"><span class="card-title">📝 Daily Summary</span><button class="btn btn-primary btn-sm" id="gen-summary" ${!modelReady ? 'disabled style="opacity:0.4;cursor:not-allowed"' : ''}>Generate</button></div>
        <div id="summary-body"><div style="color:var(--text-muted)">Click Generate for an AI-powered daily summary.</div></div>
      </div>
      <div class="card">
        <div class="card-header"><span class="card-title">📋 Standup Notes</span><button class="btn btn-primary btn-sm" id="gen-standup" ${!modelReady ? 'disabled style="opacity:0.4;cursor:not-allowed"' : ''}>Generate</button></div>
        <div id="standup-body"><div style="color:var(--text-muted)">Click Generate for standup meeting notes.</div></div>
      </div>
    </div>`;

  // Hover tooltip hint
  try {
    const mdata = await api('/api/models');
    if (!mdata.is_top_model) {
      const t = document.getElementById('summary-hint-trigger');
      t.style.display = 'inline-flex';
      t.title = `Using ${mdata.active}. Upgrade to a larger model in Settings for better summaries.`;
    }
  } catch {}
  bindDateNav($('#summary-date'), null, null, d => { currentDate = d; loadExistingSummary(); });
  currentDate = $('#summary-date').value;
  loadExistingSummary();
  $('#gen-summary').addEventListener('click', async () => {
    const body = $('#summary-body');
    body.innerHTML = '<div class="spinner"></div><div style="text-align:center;color:var(--text-muted);margin-top:8px">Gemma 4 is thinking... (think=True)</div>';
    try {
      const data = await apiPost(`/api/summary/generate?date=${currentDate}`);
      body.innerHTML = `<div class="summary-content">${data.summary?.summary || 'No summary.'}</div>`;
    } catch (err) { body.innerHTML = `<div style="color:#ef4444">Error: ${err.message}</div>`; }
  });
  $('#gen-standup').addEventListener('click', async () => {
        const body = $('#standup-body');
    body.innerHTML = '<div class="spinner"></div><div style="text-align:center;color:var(--text-muted);margin-top:8px">Generating standup notes...</div>';
    try {
      const data = await apiPost(`/api/standup/generate?date=${currentDate}`);
      body.innerHTML = `<div class="standup-box">${data.standup || 'No standup.'}</div>
        <button class="btn btn-ghost btn-sm" style="margin-top:12px" onclick="navigator.clipboard.writeText(this.previousElementSibling.textContent).then(()=>{this.textContent='✓ Copied!';setTimeout(()=>this.textContent='📋 Copy',1500)})">📋 Copy</button>`;
    } catch (err) { body.innerHTML = `<div style="color:#ef4444">Error: ${err.message}</div>`; }
  });
}

async function loadExistingSummary() {
  try {
    const data = await api(`/api/summary?date=${currentDate}`);
    if (data.generated && data.summary) {
      $('#summary-body').innerHTML = `<div class="summary-content">${data.summary.summary || ''}</div>`;
    }
    if (data.standup) {
      $('#standup-body').innerHTML = `<div class="standup-box">${data.standup}</div>
        <button class="btn btn-ghost btn-sm" style="margin-top:12px" onclick="navigator.clipboard.writeText(this.previousElementSibling.textContent).then(()=>{this.textContent='✓ Copied!';setTimeout(()=>this.textContent='📋 Copy',1500)})">📋 Copy</button>`;
    }
  } catch {}
}

// ══════════════════════════════════════════════════════════
