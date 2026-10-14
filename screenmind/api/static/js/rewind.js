//  REWIND VIEW
// ══════════════════════════════════════════════════════════
let rewindFrames = [], rewindIdx = 0, rewindInterval = null, rewindSpeed = 1000;
async function renderRewind(el) {
  el.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      <input type="date" id="rewind-date" value="${currentDate}" max="${localToday()}">
      <button class="btn btn-primary btn-sm" id="load-rewind">Load Day</button>
    </div>
    <div class="rewind-player card" id="rewind-container">
      <div class="empty-state"><div class="empty-icon">⏪</div><div class="empty-title">Day Rewind</div><div>Select a date and click Load to replay your day as a timelapse.</div></div>
    </div>`;
  bindDateNav($('#rewind-date'), null, null, () => {});
  $('#load-rewind').addEventListener('click', () => { currentDate = clampToToday($('#rewind-date').value); loadRewind(); });
}

async function loadRewind() {
  const c = $('#rewind-container');
  c.innerHTML = '<div class="spinner"></div>';
  if (rewindInterval) clearInterval(rewindInterval);
  try {
    const data = await api(`/api/rewind?date=${currentDate}`);
    rewindFrames = data.frames || [];
    if (!rewindFrames.length) { c.innerHTML = `<div class="empty-state"><div class="empty-icon">📸</div><div class="empty-title">No frames</div></div>`; return; }
    rewindIdx = 0;
    c.innerHTML = `
      <div class="frame-container"><img id="rw-img" src="${rewindFrames[0].screenshot_url}" alt="">
        <div class="overlay-caption"><span id="rw-time" style="font-weight:600"></span> — <span id="rw-app"></span> <span id="rw-summary" style="color:var(--text-secondary)"></span></div>
      </div>
      <div class="controls" style="margin-top:12px">
        <button class="btn btn-primary btn-sm" id="rw-play">▶ Play</button>
        <input type="range" class="scrub" id="rw-scrub" min="0" max="${rewindFrames.length - 1}" value="0">
        <span id="rw-counter" style="font-size:0.8rem;color:var(--text-muted);min-width:60px">1/${rewindFrames.length}</span>
        <button class="btn btn-ghost btn-sm" id="rw-speed">1x</button>
      </div>`;
    updateRewindFrame();
    $('#rw-play').addEventListener('click', toggleRewindPlay);
    $('#rw-scrub').addEventListener('input', e => { rewindIdx = +e.target.value; updateRewindFrame(); });
    $('#rw-speed').addEventListener('click', cycleSpeed);
  } catch (err) { c.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div>${err.message}</div></div>`; }
}

function updateRewindFrame() {
  const f = rewindFrames[rewindIdx]; if (!f) return;
  const img = $('#rw-img');
  img.style.opacity = '0.5';
  img.src = f.screenshot_url;
  img.onload = () => { img.style.opacity = '1'; };
  $('#rw-time').textContent = formatTime(f.timestamp);
  $('#rw-app').textContent = f.app_name || '';
  $('#rw-summary').textContent = f.summary ? `— ${f.summary}` : '';
  $('#rw-scrub').value = rewindIdx;
  $('#rw-counter').textContent = `${rewindIdx + 1}/${rewindFrames.length}`;
}

function toggleRewindPlay() {
  const btn = $('#rw-play');
  if (rewindInterval) { clearInterval(rewindInterval); rewindInterval = null; btn.textContent = '▶ Play'; }
  else {
    btn.textContent = '⏸ Pause';
    rewindInterval = setInterval(() => {
      rewindIdx++;
      if (rewindIdx >= rewindFrames.length) { rewindIdx = 0; clearInterval(rewindInterval); rewindInterval = null; btn.textContent = '▶ Play'; }
      updateRewindFrame();
    }, rewindSpeed);
  }
}

function cycleSpeed() {
  const speeds = [2000, 1000, 500, 200];
  const labels = ['0.5x', '1x', '2x', '5x'];
  const cur = speeds.indexOf(rewindSpeed);
  const next = (cur + 1) % speeds.length;
  rewindSpeed = speeds[next];
  $('#rw-speed').textContent = labels[next];
  if (rewindInterval) { clearInterval(rewindInterval); rewindInterval = null; toggleRewindPlay(); }
}

// ══════════════════════════════════════════════════════════
