//  SUMMARY & STANDUP VIEW
// ══════════════════════════════════════════════════════════
// Each day keeps its last generated summary and standup, with the time each
// was generated. The cards always show the selected day (blank when nothing
// was generated), and a response for a day you've since left is dropped.
//
// This is a sticky view: rendered once, then hidden and shown again.
// refreshSummaryView() re-syncs it on every show, and syncSummaryModelLock()
// whenever the model status changes.

let _summaryLoadSeq = 0;                                // newest loadExistingSummary() call
const _summaryBusy = { summary: null, standup: null };  // date being generated, per card
const _summaryCards = {};                               // kind → last rendered {date, state}
let _summaryModelReady = true;

const _SUMMARY_CARDS = {
  summary: {
    label: 'Summary',
    endpoint: '/api/summary/generate',
    empty: 'No summary for this day yet. Click Generate for an AI-powered daily summary.',
    spinner: 'Gemma 4 is thinking... (think=True)',
  },
  standup: {
    label: 'Standup',
    endpoint: '/api/standup/generate',
    empty: 'No standup notes for this day yet. Click Generate for standup meeting notes.',
    spinner: 'Generating standup notes...',
  },
};

async function renderSummary(el) {
  // Check model status for soft lock
  _summaryModelReady = true;
  try {
    const status = await api('/api/status');
    if (status.model && status.model.status !== 'ready') _summaryModelReady = false;
  } catch {}

  // Always rendered, hidden while the model is ready (see syncSummaryModelLock)
  const softLockHtml = `
    <div class="summary-locked-notice" id="summary-lock-notice"${_summaryModelReady ? ' style="display:none"' : ''}>
      <div class="summary-locked-icon">📝</div>
      <div class="summary-locked-text">
        <strong>Daily Summary needs Gemma 4 to generate.</strong><br>
        <a href="#" onclick="openModelHub();return false" style="color:var(--accent)">Open Model Hub</a> to download a model.
        Cached summaries from previous sessions are still shown below.
      </div>
    </div>`;

  el.innerHTML = `
    ${softLockHtml}
    <div class="summary-toolbar">
      <input type="date" id="summary-date" value="${currentDate}" max="${localToday()}">
      <span class="hint-trigger" id="summary-hint-trigger" style="display:none" title="">?</span>
      <div class="seg-pills" id="summary-date-pills"></div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
      <div class="card">
        <div class="card-header"><span class="card-title">📝 Daily Summary</span><button class="btn btn-primary btn-sm" id="gen-summary">Generate</button></div>
        <div class="summary-meta" id="summary-meta"></div>
        <div id="summary-body"></div>
      </div>
      <div class="card">
        <div class="card-header"><span class="card-title">📋 Standup Notes</span><button class="btn btn-primary btn-sm" id="gen-standup">Generate</button></div>
        <div class="summary-meta" id="standup-meta"></div>
        <div id="standup-body"></div>
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
  bindDateNav($('#summary-date'), null, null, d => _showSummaryDate(d));
  currentDate = $('#summary-date').value;
  $('#gen-summary').addEventListener('click', () => _generateSummaryPart('summary'));
  $('#gen-standup').addEventListener('click', () => _generateSummaryPart('standup'));
  loadExistingSummary();
  loadSummaryDatePills();
}

// The day this page shows. currentDate is shared with Timeline and Rewind and
// can change while this page is hidden, so Generate reads the page's own picker.
function _summaryDate() {
  return $('#summary-date')?.value || currentDate;
}

function _showSummaryDate(date) {
  currentDate = date;
  const input = $('#summary-date');
  if (input) {
    input.max = localToday();
    input.value = date;
  }
  $$('#summary-date-pills .seg-pill').forEach(b => b.classList.toggle('active', b.dataset.date === date));
  loadExistingSummary();
}

// Called each time the (sticky) view is shown again: follow a date picked on
// Timeline/Rewind, and refresh "Generated X ago", the pills and the model lock.
function refreshSummaryView() {
  if (!$('#summary-date')) return;
  syncSummaryModelLock();
  _showSummaryDate(clampToToday(currentDate, false));
  loadSummaryDatePills();
}

// Enable Generate once the model is ready (e.g. an external server started
// after this page was opened) and lock it again if the model goes away.
function syncSummaryModelLock() {
  const ready = _modelState.status === 'ready';
  if (ready === _summaryModelReady) return;
  _summaryModelReady = ready;
  const notice = $('#summary-lock-notice');
  if (notice) notice.style.display = ready ? 'none' : '';
  for (const [kind, { date, state }] of Object.entries(_summaryCards)) {
    _renderSummaryCard(kind, date, state);
  }
}

async function loadExistingSummary() {
  const date = _summaryDate();
  const seq = ++_summaryLoadSeq;
  // Clear both cards right away so the previous day's text never lingers
  _renderSummaryCard('summary', date, { loading: true });
  _renderSummaryCard('standup', date, { loading: true });
  let data;
  try {
    data = await api(`/api/summary?date=${date}`);
  } catch {
    // Not "Not generated yet": Generate would overwrite a summary that exists
    if (seq !== _summaryLoadSeq) return;
    _renderSummaryCard('summary', date, { failed: true });
    _renderSummaryCard('standup', date, { failed: true });
    return;
  }
  if (seq !== _summaryLoadSeq) return;  // another date was picked meanwhile
  _renderSummaryCard('summary', date, {
    text: data.generated && data.summary ? data.summary.summary : null,
    generatedAt: data.summary_generated_at,
  });
  _renderSummaryCard('standup', date, {
    text: data.standup || null,
    generatedAt: data.standup_generated_at,
  });
}

// state: { text, generatedAt, loading, failed, notice }
function _renderSummaryCard(kind, date, state) {
  const cfg = _SUMMARY_CARDS[kind];
  const body = $(`#${kind}-body`), meta = $(`#${kind}-meta`), btn = $(`#gen-${kind}`);
  if (!body || !meta || !btn) return;  // view not rendered
  _summaryCards[kind] = { date, state };
  const busy = _summaryBusy[kind] === date;
  const { text, generatedAt, loading, failed, notice } = state;

  let status;
  if (busy) status = 'Generating...';
  else if (loading) status = 'Loading...';
  else if (failed) status = "Couldn't load";
  else if (text && generatedAt) {
    status = `<span title="${escapeHtml(new Date(generatedAt).toLocaleString())}">Generated ${_timeAgo(generatedAt)}</span>`;
    // Generated this morning, read in the evening: nudge to refresh
    if (date === localToday() && Date.now() - new Date(generatedAt).getTime() > 3600 * 1000) {
      status += ' — regenerate to include what you did since';
    }
  } else if (text) status = 'Generated';  // saved before generation times were tracked
  else status = 'Not generated yet';
  meta.innerHTML = `${escapeHtml(_fmtSummaryDay(date))} · ${status}`;

  if (busy) {
    body.innerHTML = `<div class="spinner"></div><div style="text-align:center;color:var(--text-muted);margin-top:8px">${cfg.spinner}</div>`;
  } else if (loading) {
    body.innerHTML = '';
  } else if (failed) {
    body.innerHTML = `<div style="color:#ef4444">Couldn't load this day. <a href="#" onclick="loadExistingSummary();return false" style="color:var(--accent)">Retry</a></div>`;
  } else if (notice) {
    body.innerHTML = `<div style="color:var(--text-muted)">${escapeHtml(notice)}</div>`;
  } else if (!text) {
    body.innerHTML = `<div style="color:var(--text-muted)">${cfg.empty}</div>`;
  } else if (kind === 'summary') {
    body.innerHTML = `<div class="summary-content">${escapeHtml(text)}</div>`;
  } else {
    body.innerHTML = `<div class="standup-box">${escapeHtml(text)}</div>
      <button class="btn btn-ghost btn-sm" style="margin-top:12px" onclick="navigator.clipboard.writeText(this.previousElementSibling.textContent).then(()=>{this.textContent='✓ Copied!';setTimeout(()=>this.textContent='📋 Copy',1500)})">📋 Copy</button>`;
  }

  btn.textContent = text ? 'Regenerate' : 'Generate';
  btn.disabled = !_summaryModelReady || !!_summaryBusy[kind] || !!loading || !!failed;
}

async function _generateSummaryPart(kind) {
  const cfg = _SUMMARY_CARDS[kind];
  const date = _summaryDate();
  _summaryBusy[kind] = date;
  _renderSummaryCard(kind, date, {});
  let result;
  try {
    const data = await apiPost(`${cfg.endpoint}?date=${date}`);
    const text = kind === 'summary' ? data.summary?.summary : data.standup;
    // No generated_at = nothing to summarize (not saved), e.g. no activity
    result = data.generated_at
      ? { text, generatedAt: data.generated_at }
      : { notice: text || 'Nothing to summarize for this day.' };
  } catch (err) {
    result = { error: err.message };
  }
  _summaryBusy[kind] = null;

  const stillShown = date === _summaryDate();
  if (result.error) showToast(`${cfg.label} failed: ${result.error}`, 'warning');
  if (stillShown && !result.error) {
    _renderSummaryCard(kind, date, result);
  } else {
    // Back to what's saved for the day on screen (re-enables the button)
    if (!stillShown && result.generatedAt) {
      showToast(`${cfg.label} for ${_fmtSummaryDay(date)} is ready`, 'success');
    }
    loadExistingSummary();
  }
  if (result.generatedAt) loadSummaryDatePills();
}

// ── Date pills: today + recent days that have something generated ──
async function loadSummaryDatePills() {
  let dates = [];
  try { dates = (await api('/api/summary/dates?limit=7')).dates || []; } catch {}
  const box = $('#summary-date-pills');
  if (!box) return;
  const today = localToday();
  const byDate = new Map(dates.map(d => [d.date, d]));
  const list = [today, ...dates.map(d => d.date).filter(d => d !== today)].slice(0, 7);
  box.innerHTML = list.map(d => {
    const info = byDate.get(d) || {};
    const what = [info.summary && 'summary', info.standup && 'standup'].filter(Boolean).join(' + ') || 'nothing generated yet';
    const dots = (info.summary ? '<span class="seg-pill-dot dot-summary"></span>' : '')
      + (info.standup ? '<span class="seg-pill-dot dot-standup"></span>' : '');
    return `<button class="seg-pill${d === currentDate ? ' active' : ''}" data-date="${d}" title="${escapeHtml(_fmtSummaryDay(d))}: ${what}">${escapeHtml(_pillLabel(d))}${dots}</button>`;
  }).join('');
  box.querySelectorAll('.seg-pill').forEach(b => b.addEventListener('click', () => _showSummaryDate(b.dataset.date)));
}

function _localDateObj(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  return new Date(y, m - 1, d);
}

function _pillLabel(dateStr) {
  if (dateStr === localToday()) return 'Today';
  if (dateStr === shiftLocalDate(localToday(), -1)) return 'Yesterday';
  return _localDateObj(dateStr).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function _fmtSummaryDay(dateStr) {
  return _localDateObj(dateStr).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

// "5 min ago", "3 hours ago" — generation times are stored in local time
function _timeAgo(iso) {
  const t = new Date(iso).getTime();
  if (isNaN(t)) return '';
  const mins = Math.floor(Math.max(0, Date.now() - t) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} hour${hours > 1 ? 's' : ''} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days > 1 ? 's' : ''} ago`;
}

// ══════════════════════════════════════════════════════════
