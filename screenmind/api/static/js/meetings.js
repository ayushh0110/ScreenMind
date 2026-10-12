//  MEETINGS VIEW
// ══════════════════════════════════════════════════════════
var meetingsDate = localToday();  // local date — toISOString() would give UTC

async function renderMeetings(el) {
  // Check if current model supports audio
  const audioWarning = (_modelState.capabilities && !_modelState.capabilities.audio && _modelState.status === 'ready')
    ? `<div class="summary-locked-notice" style="margin-bottom:16px">
        <div class="summary-locked-icon">🎙️</div>
        <div class="summary-locked-text">
          <strong>Current model doesn't support audio.</strong><br>
          Meeting transcription requires Gemma 4 E2B/E4B.
          <a href="#" onclick="openModelHub();return false" style="color:var(--accent)">Switch model</a> to enable audio features.
          Existing meetings are still viewable.
        </div>
      </div>`
    : '';

  el.innerHTML = `
    ${audioWarning}
    <div class="date-nav" style="margin-bottom:20px">
      <button class="btn btn-ghost btn-sm" id="mtg-prev">◀</button>
      <input type="date" id="mtg-date" value="${meetingsDate}" max="${localToday()}">
      <button class="btn btn-ghost btn-sm" id="mtg-next">▶</button>
      <span style="margin-left:12px;color:var(--text-muted);font-size:0.85rem" id="mtg-count"></span>
      <span class="hint-trigger" id="mtg-hint-trigger" style="display:none" title="">?</span>
      <span id="mtg-recording-status" style="margin-left:auto;font-size:0.82rem"></span>
    </div>
    <div id="meetings-list"><div class="spinner"></div></div>`;
  bindDateNav($('#mtg-date'), $('#mtg-prev'), $('#mtg-next'), d => { meetingsDate = d; loadMeetings(); });
  meetingsDate = $('#mtg-date').value;
  loadMeetings();
  // Refresh status every 10s
  if (window._mtgRefresh) clearInterval(window._mtgRefresh);
  window._mtgRefresh = setInterval(() => { if (currentView === 'meetings') loadMeetingStatus(); }, 10000);
  loadMeetingStatus();

  // Transcription quality hint — removed (Gemma handles all transcription now)
  try {
    // No Whisper model selection needed — Gemma 4's native audio encoder is used
  } catch {}
}

async function loadMeetings() {
  const list = $('#meetings-list');
  list.innerHTML = '<div class="spinner"></div>';
  try {
    const data = await api(`/api/meetings?date=${meetingsDate}`);
    const meetings = data.meetings || [];
    $('#mtg-count').textContent = `${meetings.length} meeting${meetings.length !== 1 ? 's' : ''}`;
    if (!meetings.length) {
      list.innerHTML = `<div class="empty-state">
        <div class="empty-icon">🎙️</div>
        <div class="empty-title">No meetings recorded</div>
        <div style="color:var(--text-muted);font-size:0.85rem;max-width:380px;margin:0 auto;line-height:1.6">
          <p>Meeting transcription is <strong>${(await api('/api/settings')).meeting_transcription ? '✅ enabled' : '❌ disabled'}</strong>.</p>
          <p style="margin-top:8px">When enabled, ScreenMind auto-detects Zoom, Teams, Meet and other meeting apps, records audio, transcribes with Gemma 4's native audio encoder, and generates AI-powered summaries.</p>
          <p style="margin-top:8px;color:var(--accent)">Enable it in <a href="#settings" style="color:var(--accent);cursor:pointer" onclick="navigate('settings')">⚙️ Settings</a></p>
        </div>
      </div>`;
      return;
    }
    list.innerHTML = meetings.map(m => meetingDetailCard(m)).join('');
  } catch (err) {
    list.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">Error</div><div>${err.message}</div></div>`;
  }
}

async function loadMeetingStatus() {
  try {
    const status = await api('/api/meetings/status');
    const el = $('#mtg-recording-status');
    if (!el) return;
    if (status.in_meeting) {
      el.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px;color:#ef4444;font-weight:600"><span class="pulse-dot" style="background:#ef4444"></span> Recording — ${status.meeting_app || 'Meeting'} (${status.transcript_chunks} chunks)</span>`;
    } else if (status.enabled) {
      el.innerHTML = `<span style="color:var(--text-muted)">🎙️ Listening for meeting apps...</span>`;
    } else {
      el.innerHTML = `<span style="color:var(--text-muted)">❌ Transcription disabled</span>`;
    }
  } catch { /* endpoint not available */ }
}

function meetingDetailCard(m) {
  const startTime = new Date(m.start_time).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
  const endTime = m.end_time ? new Date(m.end_time).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true }) : 'ongoing';
  const duration = m.duration_minutes ? `${Math.round(m.duration_minutes)} min` : '—';
  const summaryText = (m.summary || '⏳ Generating summary...').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const transcriptText = (m.transcript || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const tid = `mtg-transcript-${m.id}`;
  const menuId = `mtg-menu-${m.id}`;
  return `
    <div class="meeting-card" id="meeting-card-${m.id}" style="animation: fadeInUp 0.4s ease forwards">
      <div class="meeting-header">
        <div class="meeting-icon">🎙️</div>
        <div>
          <div class="meeting-title">Meeting — ${(m.app_name || 'Unknown').replace(/</g, '&lt;')}</div>
          <div class="meeting-meta">${startTime} – ${endTime}</div>
        </div>
        <div class="meeting-duration">${duration}</div>
        <div class="card-menu-wrap" style="margin-left:12px">
          <button class="card-menu-trigger" style="opacity:0.6" onclick="event.stopPropagation(); toggleMtgMenu('${menuId}', this)">⋮</button>
          <div class="card-menu" id="${menuId}">
            <button class="menu-item reanalyze-item" onclick="reanalyzeMeeting(${m.id})">
              <span class="menu-icon">🔄</span> Re-analyze Summary
            </button>
            <button class="menu-item" onclick="copyMeetingTranscript(${m.id})">
              <span class="menu-icon">📋</span> Copy Transcript
            </button>
            <button class="menu-item" onclick="copyMeetingSummary(${m.id})">
              <span class="menu-icon">📝</span> Copy Summary
            </button>
            <div class="menu-divider"></div>
            <button class="menu-item delete-item" onclick="deleteMeeting(${m.id}, this)">
              <span class="menu-icon">🗑️</span> Delete Meeting
            </button>
          </div>
        </div>
      </div>
      <div class="meeting-summary" id="mtg-summary-${m.id}">${summaryText}</div>
      ${transcriptText ? `
        <button class="meeting-transcript-toggle" onclick="var t=document.getElementById('${tid}'); t.classList.toggle('open'); this.textContent = t.classList.contains('open') ? '▲ Hide transcript' : '▼ Show full transcript'">▼ Show full transcript</button>
        <div class="meeting-transcript" id="${tid}">${transcriptText}</div>
      ` : ''}
    </div>`;
}

// ── Meeting card actions ─────────────────────────────────────
function toggleMtgMenu(menuId, btn) {
  const menu = document.getElementById(menuId);
  const wasOpen = menu.classList.contains('open');
  // Close all menus first
  document.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
  document.querySelectorAll('.card-menu-trigger.active').forEach(b => b.classList.remove('active'));
  if (!wasOpen) {
    menu.classList.add('open');
    btn.classList.add('active');
    const close = (e) => { if (!menu.contains(e.target) && e.target !== btn) { menu.classList.remove('open'); btn.classList.remove('active'); document.removeEventListener('click', close); } };
    setTimeout(() => document.addEventListener('click', close), 0);
  }
}

async function reanalyzeMeeting(id) {
  document.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
  const sumEl = document.getElementById(`mtg-summary-${id}`);
  if (sumEl) sumEl.textContent = '⏳ Re-generating summary...';
  try {
    await apiPost(`/api/meetings/${id}/reanalyze`);
    showToast('Re-analyzing meeting — this takes ~15s...', 'info');
    // Poll every 5s until summary changes (Gemma takes 10-20s)
    let attempts = 0;
    const poll = setInterval(async () => {
      attempts++;
      try {
        const m = await api(`/api/meetings/${id}`);
        const s = m.summary || '';
        if (!s.includes('Re-generating') && !s.includes('interrupted') && s.length > 10) {
          clearInterval(poll);
          if (sumEl) sumEl.textContent = s;
          showToast('Summary generated!', 'success');
          loadMeetings(); // Full refresh to update card
        } else if (attempts >= 6) {
          clearInterval(poll);
          loadMeetings(); // Show whatever we got
        }
      } catch { if (attempts >= 6) clearInterval(poll); }
    }, 5000);
  } catch (err) { showToast('Re-analyze failed: ' + err.message, 'warning'); }
}

function copyMeetingTranscript(id) {
  document.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
  const el = document.getElementById(`mtg-transcript-${id}`);
  if (el) { navigator.clipboard.writeText(el.textContent); showToast('Transcript copied!', 'success'); }
  else { showToast('No transcript available', 'warning'); }
}

function copyMeetingSummary(id) {
  document.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
  const el = document.getElementById(`mtg-summary-${id}`);
  if (el) { navigator.clipboard.writeText(el.textContent); showToast('Summary copied!', 'success'); }
  else { showToast('No summary available', 'warning'); }
}

async function deleteMeeting(id, btn) {
  event.stopPropagation();  // Keep menu open
  if (!btn.dataset.confirming) {
    // First click — transform into confirm button
    btn.dataset.confirming = 'true';
    btn.querySelector('.menu-icon').textContent = '⚠️';
    btn.childNodes[1].textContent = ' Confirm Delete';
    btn.style.color = '#ef4444';
    // Auto-reset after 4s
    setTimeout(() => {
      if (btn && btn.dataset.confirming) {
        delete btn.dataset.confirming;
        btn.querySelector('.menu-icon').textContent = '🗑️';
        btn.childNodes[1].textContent = ' Delete Meeting';
        btn.style.color = '';
      }
    }, 4000);
    return;
  }
  // Second click — actually delete
  delete btn.dataset.confirming;
  try {
    await apiDelete(`/api/meetings/${id}`);
    // Close menu
    document.querySelectorAll('.card-menu.open').forEach(m => m.classList.remove('open'));
    const card = document.getElementById(`meeting-card-${id}`);
    if (card) { card.style.transition = 'opacity 0.3s, transform 0.3s'; card.style.opacity = '0'; card.style.transform = 'translateX(40px)'; setTimeout(() => card.remove(), 300); }
    showToast('Meeting deleted', 'success');
  } catch (err) { showToast('Delete failed: ' + err.message, 'warning'); }
}


// ══════════════════════════════════════════════════════════
//  SETTINGS VIEW
// ══════════════════════════════════════════════════════════
