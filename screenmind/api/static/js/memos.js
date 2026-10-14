// ══════════════════════════════════════════════════════════
//  MEMOS VIEW — Voice memos with screenshots
// ══════════════════════════════════════════════════════════

async function renderMemos(el) {
  var memosDate = currentDate;

  // Check if current model supports audio
  const memoAudioWarning = (_modelState.capabilities && !_modelState.capabilities.audio && _modelState.status === 'ready')
    ? `<div class="summary-locked-notice" style="margin-bottom:16px">
        <div class="summary-locked-icon">🎤</div>
        <div class="summary-locked-text">
          <strong>Current model doesn't support audio.</strong><br>
          Voice memo transcription requires Gemma 4 E2B/E4B.
          <a href="#" onclick="openModelHub();return false" style="color:var(--accent)">Switch model</a> to record new memos.
          Existing memos are still playable.
        </div>
      </div>`
    : '';

  el.innerHTML = `
    ${memoAudioWarning}
    <div class="date-nav" style="margin-bottom:20px">
      <button class="btn btn-ghost btn-sm" id="memo-prev">◀</button>
      <input type="date" id="memo-date" value="${memosDate}" max="${localToday()}">
      <button class="btn btn-ghost btn-sm" id="memo-next">▶</button>
      <span style="margin-left:12px;color:var(--text-muted);font-size:0.85rem" id="memo-count"></span>
    </div>
    <div class="shortcut-row" style="margin-bottom:16px">
      <span class="shortcut-key">Ctrl+Shift+V</span> Hold to record voice memo
    </div>
    <div id="memos-list"><div class="spinner"></div></div>`;

  bindDateNav($('#memo-date'), $('#memo-prev'), $('#memo-next'), function(d) { memosDate = d; loadMemos(memosDate); });
  memosDate = $('#memo-date').value;
  loadMemos(memosDate);
}

async function loadMemos(date) {
  var list = $('#memos-list');
  list.innerHTML = '<div class="spinner"></div>';
  try {
    var data = await api('/api/memos?date=' + date);
    var memos = data.memos || [];
    $('#memo-count').textContent = memos.length + ' memo' + (memos.length !== 1 ? 's' : '');

    if (!memos.length) {
      list.innerHTML = `<div class="empty-state">
        <div class="empty-icon">🎤</div>
        <div class="empty-title">No Voice Memos</div>
        <div>Press <strong>Ctrl+Shift+V</strong> (hold) to record a voice memo with screenshot.</div>
      </div>`;
      return;
    }

    list.innerHTML = '<div class="timeline">' + memos.map(function(m, i) {
      var time = formatTime(m.timestamp);
      var thumb = m.screenshot_url ? '<img class="thumb" src="' + m.screenshot_url + '" loading="lazy" onclick="openModal(\'' + m.screenshot_url + '\', ' + m.id + ')" alt="">' : '<div class="thumb"></div>';
      var audioPlayer = m.audio_url ? '<div class="memo-player" data-src="' + m.audio_url + '"><button class="memo-play-btn" onclick="event.stopPropagation(); toggleMemoAudio(this)">▶</button><span class="memo-time">0:00</span><input type="range" class="memo-scrub" value="0" min="0" max="100" oninput="seekMemo(this)"><audio preload="metadata" src="' + m.audio_url + '"></audio></div>' : '';
      var bookmarkLabel = m.bookmarked ? '★ Bookmarked' : '☆ Bookmark';
      var bookmarkClass = m.bookmarked ? 'active' : '';
      return '<div class="timeline-item" style="animation-delay:' + (i * 0.06) + 's">' +
        thumb +
        '<div class="info">' +
          '<div class="top"><span class="time">' + time + '</span><span class="app-name">Voice Memo</span><span class="badge badge-other">note</span></div>' +
          '<div class="summary">' + (m.summary || 'Transcribing...') + '</div>' +
          audioPlayer +
        '</div>' +
        '<div class="card-menu-wrap">' +
          '<button class="card-menu-trigger" onclick="event.stopPropagation(); toggleCardMenu(this)" title="Actions">⋮</button>' +
          '<div class="card-menu">' +
            '<button class="menu-item bookmark-item ' + bookmarkClass + '" onclick="event.stopPropagation(); toggleMemoBookmark(' + m.id + ', this)">' +
              '<span class="menu-icon">' + (m.bookmarked ? '★' : '☆') + '</span> ' + bookmarkLabel +
            '</button>' +
            '<button class="menu-item reanalyze-item" onclick="event.stopPropagation(); retranscribeMemo(' + m.id + ', this)">' +
              '<span class="menu-icon">↻</span> Re-transcribe' +
            '</button>' +
            '<div class="menu-divider"></div>' +
            '<button class="menu-item delete-item" onclick="event.stopPropagation(); deleteMemo(' + m.id + ', this)">' +
              '<span class="menu-icon">✕</span> Delete' +
            '</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    }).join('') + '</div>';
  } catch (err) {
    list.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><div>' + err.message + '</div></div>';
  }
}


// ── Custom Audio Player ─────────────────────────────────
window.toggleMemoAudio = function(btn) {
  var player = btn.closest('.memo-player');
  var audio = player.querySelector('audio');
  if (audio.paused) {
    // Pause all other players first
    document.querySelectorAll('.memo-player audio').forEach(function(a) { a.pause(); });
    document.querySelectorAll('.memo-play-btn').forEach(function(b) { b.textContent = '▶'; });
    audio.play();
    btn.textContent = '⏸';
    audio.ontimeupdate = function() {
      var scrub = player.querySelector('.memo-scrub');
      var time = player.querySelector('.memo-time');
      scrub.value = (audio.currentTime / audio.duration) * 100 || 0;
      var m = Math.floor(audio.currentTime / 60);
      var s = Math.floor(audio.currentTime % 60);
      time.textContent = m + ':' + (s < 10 ? '0' : '') + s;
    };
    audio.onended = function() { btn.textContent = '▶'; };
  } else {
    audio.pause();
    btn.textContent = '▶';
  }
};

window.seekMemo = function(scrub) {
  var player = scrub.closest('.memo-player');
  var audio = player.querySelector('audio');
  if (audio.duration) {
    audio.currentTime = (scrub.value / 100) * audio.duration;
  }
};

// ── Memo Actions (three-dot menu) ────────────────────────
window.retranscribeMemo = async function(id, el) {
  el.closest('.card-menu').classList.remove('open');
  el.closest('.card-menu-wrap').querySelector('.card-menu-trigger').classList.remove('active');
  showToast('↻ Re-transcribing voice memo...', 'info');
  try {
    await _postReanalyze(id);
    showToast('✓ Transcript updated!', 'success');
    var dateEl = document.getElementById('memo-date');
    if (dateEl) loadMemos(dateEl.value);
  } catch (err) {
    showToast('Re-transcription failed: ' + err.message, 'warning');
  }
};

window.toggleMemoBookmark = async function(id, el) {
  try {
    var r = await fetch('/api/activities/' + id + '/bookmark', { method: 'PUT' });
    var data = await r.json();
    el.closest('.card-menu').classList.remove('open');
    el.closest('.card-menu-wrap').querySelector('.card-menu-trigger').classList.remove('active');
    showToast(data.bookmarked ? '⭐ Bookmarked!' : 'Bookmark removed', data.bookmarked ? 'success' : 'info');
    // Reload memos to update bookmark state
    var dateEl = document.getElementById('memo-date');
    if (dateEl) loadMemos(dateEl.value);
  } catch(e) {}
};

window.deleteMemo = async function(id, btn) {
  if (!btn.classList.contains('confirm-delete')) {
    btn.innerHTML = '<span class="menu-icon">⚠</span> Confirm Delete';
    btn.classList.add('confirm-delete');
    setTimeout(function() {
      btn.innerHTML = '<span class="menu-icon">✕</span> Delete';
      btn.classList.remove('confirm-delete');
    }, 3000);
    return;
  }
  var card = btn.closest('.timeline-item');
  card.style.transform = 'translateX(100px)';
  card.style.opacity = '0';
  card.style.transition = 'all 0.3s ease';
  try {
    var r = await fetch('/api/activities/' + id, { method: 'DELETE' });
    if (!r.ok) throw new Error('Failed');
    setTimeout(function() { card.remove(); }, 300);
    showToast('Memo deleted', 'success');
    // Update count
    var countEl = document.getElementById('memo-count');
    if (countEl) {
      var remaining = document.querySelectorAll('#memos-list .timeline-item').length - 1;
      countEl.textContent = remaining + ' memo' + (remaining !== 1 ? 's' : '');
    }
  } catch (err) {
    card.style.transform = ''; card.style.opacity = '';
    showToast('Delete failed', 'warning');
  }
};
