/* ═══════════════════════════════════════════════════════════
   ScreenMind — Main Application
   SPA with physics-inspired transitions & micro-interactions
   ═══════════════════════════════════════════════════════════ */

const API = '';
// Use local date (not UTC) to avoid timezone shift issues
const _now = new Date();
let currentDate = `${_now.getFullYear()}-${String(_now.getMonth()+1).padStart(2,'0')}-${String(_now.getDate()).padStart(2,'0')}`;
let currentView = 'timeline';

// ── Lock Screen Check ──────────────────────────────────────
var _dashboardLocked = false;

async function _checkAuth() {
  try {
    var r = await fetch('/api/auth/status');
    var data = await r.json();
    // First-run: show welcome screen
    if (data.first_run) {
      _dashboardLocked = true;
      document.getElementById('welcome-screen').style.display = 'flex';
      document.getElementById('app').style.display = 'none';
      setTimeout(function() { document.getElementById('setup-pin').focus(); }, 100);
      return;
    }
    if (data.has_pin && !data.authenticated) {
      _dashboardLocked = true;
      document.getElementById('lock-screen').style.display = 'flex';
      document.getElementById('app').style.display = 'none';
      // Delay focus to ensure element is visible and painted
      setTimeout(function() { document.getElementById('pin-input').focus(); }, 100);
    }
  } catch(e) {}
}

window.completeSetup = async function(withPin) {
  var pin = '';
  if (withPin) {
    pin = document.getElementById('setup-pin').value;
    if (pin.length < 4) {
      document.getElementById('setup-pin').style.borderColor = '#ef4444';
      document.getElementById('setup-pin').setAttribute('placeholder', 'Min 4 digits');
      return;
    }
  }
  try {
    var r = await fetch('/api/auth/setup-complete', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pin: pin})
    });
    var data = await r.json();
    if (data.ok) {
      _dashboardLocked = false;
      document.getElementById('welcome-screen').style.display = 'none';
      document.getElementById('app').style.display = '';
      _initApp();
    }
  } catch(e) {
    _dashboardLocked = false;
    document.getElementById('welcome-screen').style.display = 'none';
    document.getElementById('app').style.display = '';
    _initApp();
  }
};

// Global keyboard guard — when locked, only allow typing in PIN input
document.addEventListener('keydown', function(e) {
  if (!_dashboardLocked) return;
  var pinInput = document.getElementById('pin-input');
  // Allow Enter to submit from anywhere on the lock screen
  if (e.key === 'Enter') {
    e.preventDefault();
    e.stopPropagation();
    unlockDashboard();
    return;
  }
  // Numpad fix — system-level keyboard hooks can eat numpad events
  // before they reach the browser. Manually insert the digit.
  if (e.code && e.code.startsWith('Numpad') && /^[0-9]$/.test(e.key)) {
    e.preventDefault();
    e.stopPropagation();
    pinInput.focus();
    var maxLen = parseInt(pinInput.maxLength) || 6;
    if (pinInput.value.length < maxLen) {
      pinInput.value += e.key;
    }
    return;
  }
  // If the PIN input isn't focused, redirect focus to it
  if (document.activeElement !== pinInput) {
    pinInput.focus();
  }
}, true); // 'true' = capture phase, runs before any other handler

window.unlockDashboard = async function() {
  var pin = document.getElementById('pin-input').value;
  var errEl = document.getElementById('pin-error');
  errEl.textContent = '';
  try {
    var r = await fetch('/api/auth/verify', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pin: pin})
    });
    var data = await r.json();
    if (data.ok) {
      _dashboardLocked = false;
      document.getElementById('lock-screen').style.display = 'none';
      document.getElementById('app').style.display = '';
      // Now init the app
      _initApp();
    } else {
      errEl.textContent = data.error || 'Invalid PIN';
      document.getElementById('pin-input').value = '';
      document.getElementById('pin-input').focus();
    }
  } catch(e) {
    errEl.textContent = 'Invalid PIN';
    document.getElementById('pin-input').value = '';
    document.getElementById('pin-input').focus();
  }
};

window.toggleIncognito = async function() {
  try {
    var r = await fetch('/api/incognito/toggle', { method: 'POST' });
    var data = await r.json();
    var btn = document.getElementById('incognito-btn');
    if (data.incognito) {
      btn.style.background = 'rgba(239,68,68,0.2)';
      btn.title = 'Incognito ON — click to disable';
      showToast('🕶️ Incognito mode — no recording', 'warning');
    } else {
      btn.style.background = '';
      btn.title = 'Incognito Mode';
      showToast('Incognito mode off', 'success');
    }
  } catch(e) {}
};

// ── API Client ────────────────────────────────────────────
async function api(path, opts) {
  const r = await fetch(API + path, opts || {});
  if (r.status === 401) {
    // Session expired — show lock screen
    _dashboardLocked = true;
    document.getElementById('lock-screen').style.display = 'flex';
    document.getElementById('app').style.display = 'none';
    setTimeout(function() { document.getElementById('pin-input').focus(); }, 100);
    throw new Error('Session expired');
  }
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    const e = new Error(detail.error || detail.detail || `API ${r.status}`);
    e.detail = detail.error || detail.detail;
    throw e;
  }
  return r.json();
}
async function apiPost(path) {
  return api(path, { method: 'POST' });
}
async function apiDelete(path) {
  return api(path, { method: 'DELETE' });
}

// ── Helpers ───────────────────────────────────────────────
function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }
function formatTime(ts) {
  return new Date(ts).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
}
function catColor(cat) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--cat-${cat || 'other'}`).trim() || '#64748b';
}

// ── Modal (Enhanced: split view with OCR + details) ───────
window.openModal = async function(src, activityId) {
  $('#modal-img').src = src;
  $('#modal').classList.add('visible');
  // Fetch full activity details
  if (activityId) {
    try {
      const a = await api(`/api/activity/${activityId}`);
      const time = new Date(a.timestamp).toLocaleString();
      const cat = a.category || 'other';
      const method = a.analysis_method || 'unknown';
      const methodColors = {'full': '#a78bfa', 'cache:identical': '#34d399', 'cache:minor': '#fbbf24', 'skipped': '#6b7280', 'backfill:full': '#22d3ee', 'backfill:cache:identical': '#22d3ee', 'backfill:cache:minor': '#22d3ee', 'reanalyze': '#f97316'};
      const methodColor = methodColors[method] || '#6b7280';

      // Mood emoji mapping
      const moodEmojis = {'productive': '🔥', 'distracted': '😵‍💫', 'collaborative': '🤝', 'learning': '📚', 'neutral': '😐'};
      const moodColors = {'productive': '#10b981', 'distracted': '#f59e0b', 'collaborative': '#8b5cf6', 'learning': '#3b82f6', 'neutral': '#6b7280'};
      const mood = a.mood || 'neutral';
      const moodEmoji = moodEmojis[mood] || '😐';
      const moodColor = moodColors[mood] || '#6b7280';

      // Confidence bar
      const conf = Math.round((a.confidence || 0) * 100);
      const confColor = conf >= 80 ? '#10b981' : conf >= 60 ? '#f59e0b' : '#ef4444';

      $('#modal-meta').innerHTML = `
        <div class="meta-row"><span class="time">${time}</span></div>
        <div class="meta-row"><strong>${a.app_name || 'Unknown'}</strong> <span class="badge badge-${cat}">${cat}</span> <span class="badge" style="background:${methodColor}22;color:${methodColor};border:1px solid ${methodColor}44;font-size:0.7rem;padding:2px 8px;border-radius:10px;margin-left:6px">${method}</span></div>
        <div style="display:flex;align-items:center;gap:12px;margin-top:8px">
          <span style="display:inline-flex;align-items:center;gap:4px;background:${moodColor}18;color:${moodColor};border:1px solid ${moodColor}33;padding:3px 10px;border-radius:10px;font-size:0.75rem;font-weight:500">${moodEmoji} ${mood}</span>
          <div style="display:flex;align-items:center;gap:6px;flex:1">
            <span style="font-size:0.7rem;color:var(--text-muted)">Confidence</span>
            <div style="flex:1;height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden;max-width:120px">
              <div style="width:${conf}%;height:100%;background:${confColor};border-radius:3px;transition:width 0.5s ease"></div>
            </div>
            <span style="font-size:0.7rem;color:${confColor};font-weight:600">${conf}%</span>
          </div>
        </div>
        ${a.active_url ? `<div style="margin-top:6px"><a href="${a.active_url}" target="_blank" rel="noopener" style="font-size:0.75rem;color:#60a5fa;text-decoration:none;word-break:break-all;display:inline-flex;align-items:center;gap:4px" title="${a.active_url}">🔗 ${a.active_url.length > 80 ? a.active_url.substring(0, 80) + '…' : a.active_url}</a></div>` : ''}`;
      // Modal shows detailed context (timeline cards already show the short summary)
      $('#modal-summary').textContent = a.details || a.summary || 'No analysis yet';

      $('#modal-ocr').textContent = a.scene_description || 'No scene description yet';
    } catch { $('#modal-summary').textContent = 'Unable to load details'; }
  }
};
window.closeModal = function(e) {
  if (e && e.target && e.target !== $('#modal')) return;
  $('#modal').classList.remove('visible');
};
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

// ── Toast Notifications ───────────────────────────────────
window.showToast = function(message, type = 'info') {
  const container = $('#toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => { toast.classList.add('exit'); setTimeout(() => toast.remove(), 300); }, 3000);
};

// ── Text Highlighting ─────────────────────────────────────
function highlightText(text, query) {
  if (!text || !query) return text || '';
  const words = query.trim().split(/\s+/).filter(w => w.length > 2);
  if (!words.length) return text;
  const pattern = words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  return text.replace(new RegExp(`(${pattern})`, 'gi'), '<mark>$1</mark>');
}

// ── Sliding Nav Indicator ─────────────────────────────────
function moveIndicator(btn) {
  const indicator = $('#nav-indicator');
  const nav = $('#sidebar-nav');
  const navRect = nav.getBoundingClientRect();
  const btnRect = btn.getBoundingClientRect();
  const y = btnRect.top - navRect.top;
  indicator.style.transform = `translateY(${y}px)`;
  indicator.style.height = `${btnRect.height}px`;
}

// ── Router with animated transitions ──────────────────────
// Chat and summary are "sticky" — their DOM persists across navigation
// so in-flight SSE streams and message history survive tab switches.
const _stickyViews = new Set(['chat', 'summary']);

function navigate(view) {
  currentView = view;
  window.location.hash = view;

  // Close Model Hub overlay on navigation
  closeModelHub();

  // Show/hide timeline pill (only visible on Timeline)
  const pill = document.getElementById('mh-timeline-pill');
  if (pill) pill.style.display = view === 'timeline' ? '' : 'none';

  // Update nav
  const btns = $$('.nav-item');
  btns.forEach(n => n.classList.toggle('active', n.dataset.view === view));
  const activeBtn = $(`[data-view="${view}"]`);
  if (activeBtn) moveIndicator(activeBtn);

  // Update header
  const titles = { timeline:'Timeline', search:'Search', bookmarks:'Bookmarks', analytics:'Analytics', rewind:'Day Rewind', summary:'Summary & Standup', chat:'Chat', meetings:'Meetings', memos:'Voice Memos', agents:'Agents', settings:'Settings' };
  $('#page-title').textContent = titles[view] || view;

  const el = $('#content');

  // Clear initial loading spinner on first navigate
  const spinner = el.querySelector(':scope > .spinner');
  if (spinner) spinner.remove();

  // Hide all sticky containers
  el.querySelectorAll('.view-sticky').forEach(c => c.style.display = 'none');

  // Hide the ephemeral slot
  let ephemeral = el.querySelector('.view-ephemeral');

  if (_stickyViews.has(view)) {
    if (ephemeral) ephemeral.style.display = 'none';

    let container = el.querySelector(`[data-view="${view}"]`);
    if (!container) {
      container = document.createElement('div');
      container.className = 'view-sticky view-enter';
      container.dataset.view = view;
      el.appendChild(container);
      const fns = { chat: renderChat, summary: renderSummary };
      (fns[view])(container);
    } else {
      container.style.display = '';
      if (view === 'chat') {
        const chatInput = document.getElementById('chat-input');
        if (chatInput) chatInput.focus();
      }
    }
  } else {
    if (!ephemeral) {
      ephemeral = document.createElement('div');
      ephemeral.className = 'view-ephemeral';
      el.appendChild(ephemeral);
    }
    ephemeral.style.display = '';
    ephemeral.innerHTML = '';
    const wrapper = document.createElement('div');
    wrapper.className = 'view-enter';
    ephemeral.appendChild(wrapper);

    const fns = { timeline: renderTimeline, search: renderSearch, bookmarks: renderBookmarks, analytics: renderAnalytics, rewind: renderRewind, meetings: renderMeetings, memos: renderMemos, agents: renderAgents, settings: renderSettings };
    (fns[view] || renderTimeline)(wrapper);
  }
}

$('#sidebar-nav').addEventListener('click', e => {
  const btn = e.target.closest('.nav-item');
  if (btn) navigate(btn.dataset.view);
});

// ── Status Polling ────────────────────────────────────────
async function pollStatus() {
  try {
    const s = await api('/api/status');
    const dot = $('#status-dot');
    const txt = $('#status-text');
    const pauseBtn = $('#pause-btn');
    const pauseIcon = $('#pause-icon');
    const pauseLabel = $('#pause-label');
    if (s.capture?.paused) {
      dot.className = 'status-dot paused'; txt.textContent = 'Ready';
      if (pauseBtn) { pauseBtn.classList.add('paused'); pauseIcon.textContent = '\u25b6'; pauseLabel.textContent = 'Start Capturing'; }
    } else {
      const count = s.capture?.captures || 0;
      dot.className = 'status-dot'; txt.textContent = `Capturing (${count})`;
      if (pauseBtn) { pauseBtn.classList.remove('paused'); pauseIcon.textContent = '\u23f8'; pauseLabel.textContent = 'Stop Capturing'; }
    }

    // ── Model state tracking (unified _modelState) ──
    if (s.model) {
      const prev = _modelState.status;
      _modelState.status = s.model.status;
      _modelState.activeModel = s.model.active_model;
      _modelState.modelDownloaded = s.model.model_downloaded;
      _modelState.download = s.model.download;
      _modelState.message = s.model.message || '';
      _modelState.externalModel = s.model.external_model || null;
      if (s.model.capabilities) _modelState.capabilities = s.model.capabilities;

      if (prev !== 'ready' && _modelState.status === 'ready') {
        showToast('\ud83c\udf89 Model ready! Chat is now available.', 'success');
      }

      // Adaptive poll: 5s during lifecycle, 15s otherwise (#7)
      const fast = ['downloading', 'starting', 'cancelling'].includes(_modelState.status);
      _setPollInterval(fast ? 5000 : 15000);

      _updateModelUI();
    }
  } catch { $('#status-text').textContent = 'Offline'; $('#status-dot').className = 'status-dot error'; }
}

// ── Start / Stop Capture Toggle ───────────────────────────
window.toggleCapture = async function() {
  const btn = $('#pause-btn');
  const isPaused = btn.classList.contains('paused');
  try {
    await apiPost(isPaused ? '/api/capture/resume' : '/api/capture/pause');
    showToast(isPaused ? 'Capture started!' : 'Capture stopped.', isPaused ? 'success' : 'warning');
    pollStatus();
  } catch (err) { showToast('Failed to toggle capture', 'warning'); }
};

// ── Animated Counter ──────────────────────────────────────
function animateValue(el, end, duration = 600) {
  const start = 0;
  const startTime = performance.now();
  const isFloat = String(end).includes('.');
  function update(now) {
    const t = Math.min((now - startTime) / duration, 1);
    const eased = 1 - Math.pow(1 - t, 3);
    const val = start + (end - start) * eased;
    el.textContent = isFloat ? val.toFixed(1) : Math.round(val);
    if (t < 1) requestAnimationFrame(update);
  }
  requestAnimationFrame(update);
}

// ══════════════════════════════════════════════════════════
//  MODEL HUB — Unified state + overlay + pill + dispatcher
// ══════════════════════════════════════════════════════════

const _modelState = {
  status: 'ready',
  activeModel: null,
  modelDownloaded: false,
  download: null,
  message: '',
  models: [],
  capabilities: null,  // null until first poll — prevents false audio warnings
};

// Adaptive poll interval — faster during active lifecycle
let _pollIntervalId = null;
let _currentPollMs = 15000;
function _setPollInterval(ms) {
  if (ms === _currentPollMs && _pollIntervalId) return;
  _currentPollMs = ms;
  if (_pollIntervalId) clearInterval(_pollIntervalId);
  _pollIntervalId = setInterval(pollStatus, ms);
}

function _formatBytes(bytes) {
  if (bytes > 1024*1024*1024) return (bytes/(1024*1024*1024)).toFixed(1) + ' GB';
  if (bytes > 1024*1024) return Math.round(bytes/(1024*1024)) + ' MB';
  if (bytes > 1024) return Math.round(bytes/1024) + ' KB';
  return bytes + ' B';
}

// Named Escape handler — no stacking
function _modelHubEscHandler(e) {
  if (e.key === 'Escape') closeModelHub();
}

window.openModelHub = async function() {
  const overlay = document.getElementById('mh-overlay');
  if (!overlay) return;
  overlay.classList.add('visible');
  document.addEventListener('keydown', _modelHubEscHandler);
  await _renderModelHubCards();
  _updateModelHubFooter();
};

window.closeModelHub = function() {
  const overlay = document.getElementById('mh-overlay');
  if (!overlay) return;
  overlay.classList.remove('visible');
  document.removeEventListener('keydown', _modelHubEscHandler);
};

async function _renderModelHubCards() {
  const container = document.getElementById('mh-cards');
  if (!container) return;
  try {
    const data = await api('/api/models');
    _modelState.models = data.models || [];
  } catch {
    container.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:20px">Could not load models</div>';
    return;
  }

  const isLifecycleActive = ['downloading', 'starting', 'cancelling'].includes(_modelState.status);

  // External/unknown model warning card
  let externalCard = '';
  if (_modelState.externalModel && _modelState.status === 'ready') {
    externalCard = `
      <div class="mh-card" style="border:1px solid rgba(251,191,36,0.4);background:rgba(251,191,36,0.06);animation-delay:0s">
        <div class="mh-card-top">
          <div class="mh-card-info">
            <div class="mh-card-name">\u26a0\ufe0f ${_modelState.externalModel}
              <span class="mh-badge" style="background:rgba(251,191,36,0.2);color:#fbbf24">External</span>
            </div>
            <div class="mh-card-meta" style="color:#fbbf24">Unknown model — may lack vision or audio support. Voice memos and screen analysis may not work correctly.</div>
          </div>
        </div>
        <div class="mh-card-caps">
          <span class="mh-card-cap" style="opacity:0.5">\u2753 Audio unknown</span>
          <span class="mh-card-cap" style="opacity:0.5">\u2753 Vision unknown</span>
        </div>
      </div>`;
  }

  container.innerHTML = externalCard + _modelState.models.map((m, i) => {
    const isDownloading = isLifecycleActive && _modelState.download && _modelState.download.model === m.key;

    // Build variant rows — each variant is its own row with individual actions
    const variantRows = (m.variants || []).map(v => {
      const isThisActive = m.status === 'active' && v.quant === m.active_variant;
      const isThisDownloaded = v.downloaded;

      // Badge
      let vBadge = '';
      if (isThisActive) vBadge = '<span class="mh-badge mh-badge-active">\u2713 Active</span>';
      else if (isThisDownloaded) vBadge = '<span class="mh-badge mh-badge-downloaded">Downloaded</span>';

      // Action button
      let vAction = '';
      if (isDownloading) {
        vAction = '<button class="mh-action-btn" disabled>Busy</button>';
      } else if (isLifecycleActive) {
        vAction = '<button class="mh-action-btn" disabled>Busy</button>';
      } else if (isThisActive) {
        vAction = '';  // No action for active variant
      } else if (isThisDownloaded) {
        vAction = `<button class="mh-action-btn mh-btn-switch" onclick="hubSwitchVariant('${m.key}', '${v.quant}')">Switch</button>`;
      } else {
        vAction = `<button class="mh-action-btn mh-btn-download" onclick="hubDownloadVariant('${m.key}', '${v.quant}')">Download</button>`;
      }

      // Delete button — enabled for downloaded non-active, disabled for active
      let vDelete = '';
      if (isThisActive) {
        vDelete = '<button class="mh-btn-delete" disabled title="Cannot delete active variant">\ud83d\uddd1</button>';
      } else if (isThisDownloaded && !isLifecycleActive) {
        vDelete = `<button class="mh-btn-delete" onclick="hubDeleteVariant('${m.key}', '${v.quant}')" title="Delete variant">\ud83d\uddd1</button>`;
      }

      return `
        <div class="mh-variant-item ${isThisActive ? 'mh-variant-active' : ''}">
          <div class="mh-variant-info">
            <span class="mh-variant-quant">${v.quant}</span>
            <span class="mh-variant-size">${v.file_size}</span>
            ${vBadge}
          </div>
          <div class="mh-variant-actions">
            ${vDelete}
            ${vAction}
          </div>
        </div>`;
    }).join('');

    // Download progress bar (shown at model level during download)
    let progressHtml = '';
    if (isDownloading) {
      const bytes = _modelState.download ? _modelState.download.downloaded_bytes || 0 : 0;
      progressHtml = `
        <div class="mh-progress mh-progress-indeterminate" data-progress-key="${m.key}">
          <div class="mh-progress-bar"><div class="mh-progress-fill"></div></div>
          <div class="mh-progress-text">
            <span class="mh-progress-bytes">\ud83d\udce6 ${_formatBytes(bytes)} downloaded</span>
            <span>\u2713 Auto-unlocks when ready</span>
          </div>
        </div>`;
    }

    return `
      <div class="mh-card" data-model-key="${m.key}" style="animation-delay:${i * 0.08}s">
        <div class="mh-card-top">
          <div class="mh-card-info">
            <div class="mh-card-name">${m.name} ${m.tier >= 2 ? '\u2b50' : ''}
              ${isDownloading ? '<span class="mh-badge mh-badge-downloading">Downloading...</span>' : ''}
            </div>
            <div class="mh-card-meta">${m.size} params \u00b7 ${m.vram} VRAM \u00b7 ${m.quality}</div>
          </div>
          ${isDownloading ? '<button class="mh-action-btn mh-btn-cancel" onclick="hubCancelDownload()">Cancel</button>' : ''}
        </div>
        <div class="mh-card-caps">
          ${m.audio ? '<span class="mh-card-cap">\ud83d\udd0a Audio</span>' : '<span class="mh-card-cap" style="opacity:0.4">\ud83d\udd07 No Audio</span>'}
          ${m.vision ? '<span class="mh-card-cap">\ud83d\udc41 Vision</span>' : ''}
        </div>
        <div class="mh-variant-list">
          ${variantRows}
        </div>
        ${progressHtml}
      </div>`;
  }).join('');
}

function _updateModelHubOverlay() {
  const overlay = document.getElementById('mh-overlay');
  if (!overlay || !overlay.classList.contains('visible')) return;

  // Update download progress bytes in-place (avoids full re-render flicker)
  if (_modelState.download && _modelState.download.model) {
    const card = overlay.querySelector(`[data-model-key="${_modelState.download.model}"].mh-card`);
    if (card) {
      const bytesEl = card.querySelector('.mh-progress-bytes');
      if (bytesEl) {
        const bytes = _modelState.download.downloaded_bytes || 0;
        bytesEl.textContent = '\ud83d\udce6 ' + _formatBytes(bytes) + ' downloaded';
      }
    }
  }

  _updateModelHubFooter();
}

function _updateModelHubFooter() {
  const footer = document.getElementById('mh-footer');
  if (!footer) return;
  const dot = footer.querySelector('.mh-footer-dot');
  const text = footer.querySelector('.mh-footer-text');
  if (!dot || !text) return;

  const st = _modelState;
  if (st.status === 'ready') {
    if (st.externalModel) {
      dot.className = 'mh-footer-dot mh-dot-starting';
      text.innerHTML = 'Running \u00b7 ' + st.externalModel + ' (external)';
    } else {
      const info = st.models.find(m => m.key === st.activeModel);
      const name = info ? info.name : (st.activeModel || 'Unknown');
      dot.className = 'mh-footer-dot mh-dot-ready';
      text.innerHTML = 'Running \u00b7 ' + name + ' loaded';
    }
  } else if (st.status === 'starting') {
    dot.className = 'mh-footer-dot mh-dot-starting';
    text.innerHTML = 'Starting server...';
  } else if (st.status === 'error') {
    dot.className = 'mh-footer-dot mh-dot-error';
    text.innerHTML = 'Server stopped \u00b7 <a onclick="retryModelStart()">Retry</a>';
  } else if (st.status === 'downloading') {
    dot.className = 'mh-footer-dot mh-dot-download';
    text.innerHTML = 'Downloading...';
  } else {
    dot.className = 'mh-footer-dot mh-dot-nomodel';
    text.innerHTML = 'No model installed';
  }
}

window.hubDownloadVariant = async function(key, quant) {
  _modelState.status = 'downloading';
  _modelState.download = { model: key, downloaded_bytes: 0, message: 'Starting download...' };
  _updateModelUI();
  try {
    const res = await fetch('/api/models/pull', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, quant }),
    });
    if (res.status === 409) {
      const j = await res.json();
      showToast(j.error || 'Download already in progress', 'warning');
      try {
        const status = await api('/api/status');
        if (status.model) {
          _modelState.status = status.model.status;
          _modelState.download = status.model.download;
          _modelState.message = status.model.message || '';
          _updateModelUI();
        }
      } catch {}
    } else if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      showToast(j.error || 'Download failed to start', 'warning');
      _modelState.status = 'no_model';
      _modelState.download = null;
      _updateModelUI();
    }
  } catch (e) {
    showToast('Failed to start download: ' + e.message, 'warning');
    _modelState.status = 'no_model';
    _modelState.download = null;
    _updateModelUI();
  }
};

window.hubSwitchVariant = async function(key, quant) {
  // Audio capability check
  if (typeof _confirmAudioLoss === 'function' && !_confirmAudioLoss(key)) return;
  // Confirm server restart
  if (!confirm('Switching requires a server restart. Continue?')) return;
  // Save variant preference then switch model
  try {
    await fetch('/api/models/variant', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, quant }),
    });
    // If it's a different model, switch to it; if same model, variant endpoint already restarts
    if (_modelState.activeModel !== key) {
      await fetch('/api/models/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key }),
      });
    }
    showToast(`Switching to ${key} (${quant})...`, 'info');
    await _renderModelHubCards();
  } catch (e) {
    showToast('Failed to switch: ' + e.message, 'warning');
  }
};

window.hubDeleteVariant = async function(key, quant) {
  if (!confirm(`Delete the ${quant} variant? The model file will be removed from disk.`)) return;
  try {
    const res = await fetch('/api/models/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, quant }),
    });
    const j = await res.json();
    if (res.ok) {
      showToast(j.message || 'Variant deleted', 'info');
      await _renderModelHubCards();
    } else {
      showToast(j.error || 'Delete failed', 'warning');
    }
  } catch (e) {
    showToast('Delete failed: ' + e.message, 'warning');
  }
};

// Shared audio-loss confirmation — called by both overlay and Settings switch/install
function _confirmAudioLoss(key) {
  const m = _modelState.models.find(x => x.key === key);
  if (m && m.audio === false) {
    return confirm(
      `${m.name} has no audio support.\n\n` +
      `Voice memos and meeting transcription will be unavailable ` +
      `until you switch back to Gemma 4 E2B/E4B.\n\nContinue?`
    );
  }
  return true;
}


window.retryModelStart = async function() {
  showToast('Retrying server start...', 'info');
  try { await fetch('/api/models/restart', { method: 'POST' }); } catch (e) { showToast('Retry failed: ' + e.message, 'warning'); }
};

window.hubCancelDownload = async function() {
  try {
    const res = await fetch('/api/models/cancel', { method: 'POST' });
    if (res.ok) {
      showToast('Cancelling download...', 'warning');
      // Don't jump straight to idle — use 'cancelling' to avoid
      // race where user clicks Download before backend releases lock (#4)
      _modelState.status = 'cancelling';
      _modelState.download = null;
      _modelState.message = 'Cancelling...';
      _updateModelUI();
      // Backend releases lock within ~2s; next poll will set real state
    } else {
      showToast('No active download to cancel', 'info');
    }
  } catch (e) {
    showToast('Cancel failed: ' + e.message, 'warning');
  }
};

// ── Timeline Pill ─────────────────────────────────────────
function _injectTimelinePill() {
  if (document.getElementById('mh-timeline-pill')) return;
  const headerActions = document.getElementById('header-actions');
  if (!headerActions) return;
  const pill = document.createElement('button');
  pill.id = 'mh-timeline-pill';
  pill.className = 'mh-trigger';
  pill.onclick = function() { openModelHub(); };
  pill.innerHTML = '<span class="mh-trigger-icon">\ud83e\udde0</span><span class="mh-trigger-text">Model Hub</span><span class="mh-trigger-dot mh-dot-ready"></span>';
  headerActions.appendChild(pill);
  _updateTimelinePill();
}

function _updateTimelinePill() {
  const pill = document.getElementById('mh-timeline-pill');
  if (!pill) return;
  const textEl = pill.querySelector('.mh-trigger-text');
  const dotEl = pill.querySelector('.mh-trigger-dot');
  if (!textEl || !dotEl) return;

  const st = _modelState;
  if (st.status === 'ready') {
    if (st.externalModel) {
      // Unknown external model — amber dot
      textEl.textContent = st.externalModel;
      dotEl.className = 'mh-trigger-dot mh-dot-starting';
    } else {
      const info = st.models.find(m => m.key === st.activeModel);
      textEl.textContent = info ? info.name : (st.activeModel || 'Model Hub');
      dotEl.className = 'mh-trigger-dot mh-dot-ready';
    }
  } else if (st.status === 'downloading') {
    textEl.textContent = 'Downloading...';
    dotEl.className = 'mh-trigger-dot mh-dot-download';
  } else if (st.status === 'starting') {
    textEl.textContent = 'Starting...';
    dotEl.className = 'mh-trigger-dot mh-dot-starting';
  } else if (st.status === 'cancelling') {
    textEl.textContent = 'Cancelling...';
    dotEl.className = 'mh-trigger-dot mh-dot-starting';
  } else if (st.status === 'error') {
    textEl.textContent = 'Error';
    dotEl.className = 'mh-trigger-dot mh-dot-error';
  } else {
    textEl.textContent = 'No Model';
    dotEl.className = 'mh-trigger-dot mh-dot-nomodel';
  }
}

// ── Unified Model UI Dispatcher ───────────────────────────
function _updateModelUI() {
  if (typeof _updateChatLockState === 'function') _updateChatLockState();
  _updateModelHubOverlay();
  _updateTimelinePill();

  // Nav badge: warning dot on Chat
  const chatNav = document.querySelector('[data-view="chat"] .nav-badge-warning');
  if (_modelState.status === 'ready') {
    if (chatNav) chatNav.remove();
  } else {
    const chatNavItem = document.querySelector('[data-view="chat"]');
    if (chatNavItem && !chatNavItem.querySelector('.nav-badge-warning')) {
      const badge = document.createElement('span');
      badge.className = 'nav-badge-warning';
      chatNavItem.appendChild(badge);
    }
  }

  // Settings model list — in-place badge/button update (avoids flicker #5)
  if (currentView === 'settings') {
    _updateSettingsInPlace();
  }
}

// In-place Settings model list update — only re-render on state transitions
let _lastSettingsState = '';
function _updateSettingsInPlace() {
  const listEl = document.getElementById('model-list');
  if (!listEl) return;

  // Patch download progress bytes in-place every poll (no full re-render)
  if (_modelState.download && _modelState.download.model) {
    const bytesEls = listEl.querySelectorAll('[data-progress-bytes]');
    bytesEls.forEach(el => {
      const bytes = _modelState.download.downloaded_bytes || 0;
      const bytesStr = typeof _formatBytes === 'function' ? _formatBytes(bytes) : bytes + ' B';
      el.textContent = '\ud83d\udce6 ' + bytesStr;
    });
  }

  // Full re-render only when state actually changed (avoids redundant API calls)
  const stateKey = _modelState.status + '|' + _modelState.activeModel + '|' +
    (_modelState.models || []).map(m => m.status + m.active_variant).join(',');
  if (stateKey !== _lastSettingsState) {
    _lastSettingsState = stateKey;
    if (typeof loadModels === 'function') loadModels();
  }
}
