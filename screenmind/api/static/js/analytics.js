//  ANALYTICS VIEW
// ══════════════════════════════════════════════════════════
let categoryChart, appsChart;
async function renderAnalytics(el) {
  el.innerHTML = `
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:20px">
      <div class="range-toggle" id="range-toggle">
        <button class="active" data-range="day">Day</button>
        <button data-range="week">Week</button>
        <button data-range="month">Month</button>
      </div>
    </div>
    <div class="stats-grid" id="stats-grid"></div>
    <div class="charts-grid">
      <div class="card"><div class="card-header"><span class="card-title">Activity Categories</span></div><canvas id="cat-chart"></canvas></div>
      <div class="card"><div class="card-header"><span class="card-title">Top Apps</span></div><canvas id="apps-chart"></canvas></div>
    </div>`;
  $('#range-toggle').addEventListener('click', e => {
    const btn = e.target.closest('button');
    if (btn) { $$('#range-toggle button').forEach(b => b.classList.remove('active')); btn.classList.add('active'); loadAnalytics(btn.dataset.range); }
  });
  loadAnalytics('day');
}

async function loadAnalytics(range) {
  try {
    const data = await api(`/api/stats?range=${range}`);
    const cats = data.category_breakdown || {};
    const apps = data.top_apps || {};
    const total = data.total_activities || 0;
    const hours = (total * 30 / 3600).toFixed(1);
    const topCat = Object.keys(cats).sort((a, b) => cats[b] - cats[a])[0] || '—';
    const meetingsCount = data.meetings_count || 0;
    const meetingsMins = data.meetings_minutes || 0;
    const meetingsHrs = meetingsMins >= 60 ? (meetingsMins / 60).toFixed(1) + 'h' : meetingsMins + 'm';

    $('#stats-grid').innerHTML = `
      <div class="stat-card" style="animation-delay:0s"><div class="stat-icon">📸</div><div class="stat-value" data-count="${total}">0</div><div class="stat-label">Activities</div></div>
      <div class="stat-card" style="animation-delay:0.1s"><div class="stat-icon">⏱️</div><div class="stat-value" data-count="${hours}">0</div><div class="stat-label">Hours Tracked</div></div>
      <div class="stat-card" style="animation-delay:0.2s"><div class="stat-icon">🏆</div><div class="stat-value">${topCat}</div><div class="stat-label">Top Category</div></div>
      <div class="stat-card" style="animation-delay:0.3s"><div class="stat-icon">💻</div><div class="stat-value" data-count="${Object.keys(apps).length}">0</div><div class="stat-label">Apps Used</div></div>
      <div class="stat-card" style="animation-delay:0.4s"><div class="stat-icon">🎙️</div><div class="stat-value" data-count="${meetingsCount}">0</div><div class="stat-label">Meetings</div></div>
      <div class="stat-card" style="animation-delay:0.5s"><div class="stat-icon">⏳</div><div class="stat-value">${meetingsCount > 0 ? meetingsHrs : '—'}</div><div class="stat-label">Meeting Time</div></div>`;

    // Status breakdown card
    const sb = data.status_breakdown || {};
    const okCount = sb.ok || 0;
    const pendingCount = sb.pending || 0;
    const skippedCount = sb.skipped || 0;
    const failedCount = sb.failed || 0;
    const deadCount = sb.dead || 0;
    const totalAll = okCount + pendingCount + skippedCount + failedCount + deadCount;
    const pct = totalAll > 0 ? Math.round((okCount / totalAll) * 100) : 0;

    // Remove previous status card if switching range
    const oldCard = document.getElementById('status-breakdown-card');
    if (oldCard) oldCard.remove();

    if (totalAll > 0) {
      const statusCard = document.createElement('div');
      statusCard.className = 'card';
      statusCard.id = 'status-breakdown-card';
      statusCard.style.cssText = 'animation-delay:0.6s; margin-top: 16px;';
      statusCard.innerHTML = `
        <div class="card-header"><span class="card-title">Analysis Status</span><span style="color:#64748b;font-size:13px">${pct}% analyzed</span></div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;padding:4px 0 8px">
          <div style="display:flex;align-items:center;gap:6px"><span style="color:#10b981">✅</span><span style="color:#e2e8f0;font-weight:500">${okCount}</span><span style="color:#64748b;font-size:13px">Analyzed</span></div>
          ${pendingCount > 0 ? `<div style="display:flex;align-items:center;gap:6px"><span style="color:#f59e0b">⏳</span><span style="color:#e2e8f0;font-weight:500">${pendingCount}</span><span style="color:#64748b;font-size:13px">Pending</span></div>` : ''}
          ${skippedCount > 0 ? `<div style="display:flex;align-items:center;gap:6px"><span style="color:#6366f1">⏭️</span><span style="color:#e2e8f0;font-weight:500">${skippedCount}</span><span style="color:#64748b;font-size:13px">Skipped</span></div>` : ''}
          ${failedCount > 0 ? `<div style="display:flex;align-items:center;gap:6px"><span style="color:#ef4444">❌</span><span style="color:#e2e8f0;font-weight:500">${failedCount}</span><span style="color:#64748b;font-size:13px">Failed</span></div>` : ''}
          ${deadCount > 0 ? `<div style="display:flex;align-items:center;gap:6px"><span style="color:#6b7280">💀</span><span style="color:#e2e8f0;font-weight:500">${deadCount}</span><span style="color:#64748b;font-size:13px">Dead</span></div>` : ''}
        </div>
        <div style="width:100%;height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden">
          <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,#10b981,#34d399);border-radius:3px;transition:width 0.8s ease"></div>
        </div>`;
      const grid = $('#stats-grid');
      grid.parentNode.insertBefore(statusCard, grid.nextElementSibling);
    }

    // Animate counters
    $$('.stat-value[data-count]').forEach(el => {
      animateValue(el, parseFloat(el.dataset.count));
    });

    // Charts
    if (categoryChart) categoryChart.destroy();
    const catLabels = Object.keys(cats);
    categoryChart = new Chart($('#cat-chart'), {
      type: 'doughnut',
      data: { labels: catLabels, datasets: [{ data: Object.values(cats), backgroundColor: catLabels.map(c => catColor(c)), borderWidth: 0 }] },
      options: { responsive: true, animation: { animateRotate: true, duration: 800 }, plugins: { legend: { position: 'bottom', labels: { color: '#94a3b8', padding: 12, font: { family: 'Inter' } } } } }
    });

    if (appsChart) appsChart.destroy();
    const appLabels = Object.keys(apps).slice(0, 8);
    appsChart = new Chart($('#apps-chart'), {
      type: 'bar',
      data: { labels: appLabels, datasets: [{ data: appLabels.map(a => apps[a]), backgroundColor: '#8b5cf6', borderRadius: 6 }] },
      options: {
        indexAxis: 'y', responsive: true, animation: { duration: 800 },
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: '#64748b' }, grid: { color: 'rgba(255,255,255,0.04)' } }, y: { ticks: { color: '#94a3b8', font: { family: 'Inter' } }, grid: { display: false } } }
      }
    });
  } catch {}
}

// ══════════════════════════════════════════════════════════
