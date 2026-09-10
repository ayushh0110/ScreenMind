async function renderSettings(el) {
  el.innerHTML = '<div class="spinner"></div>';
  let cfg, startupStatus;
  try {
    [cfg, startupStatus] = await Promise.all([
      api('/api/settings'),
      api('/api/startup/status').catch(() => ({ installed: false }))
    ]);
  } catch {
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">Cannot load settings</div></div>';
    return;
  }

  function _sec(icon, title) { return '<div class="settings-section"><span class="settings-section-icon">' + icon + '</span><span class="settings-section-title">' + title + '</span></div>'; }
  function _sw(id, checked) { return '<label class="toggle-switch"><input type="checkbox" id="' + id + '" ' + (checked ? 'checked' : '') + '><span class="toggle-slider"></span></label>'; }
  function _rp(name, val, label, cur) { return '<label class="radio-pill ' + (String(cur) === String(val) ? 'active' : '') + '"><input type="radio" name="' + name + '" value="' + val + '" ' + (String(cur) === String(val) ? 'checked' : '') + '> ' + label + '</label>'; }

  var wh_events = (cfg.webhook_events || 'daily_summary,standup').split(',');

  el.innerHTML = '<div class="settings-grid">'

  // ── KEYBOARD SHORTCUTS ──
  + _sec('&#9000;', 'Keyboard Shortcuts')
  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Bookmark Hotkey</div><div class="settings-desc">Capture and bookmark the current screen instantly</div></div></div>'
  + '<div style="display:flex;align-items:center;gap:12px"><input type="text" id="bookmark-hotkey-input" class="hotkey-input" value="' + (cfg.bookmark_hotkey || 'ctrl+shift+b') + '" readonly>'
  + '<button class="btn btn-sm" onclick="startHotkeyCapture(\'bookmark-hotkey-input\')">Record</button>'
  + '<button class="btn btn-sm" style="color:var(--text-muted)" onclick="document.getElementById(\'bookmark-hotkey-input\').value=\'ctrl+shift+b\'">Reset</button></div></div>'

  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Pause / Resume Hotkey</div><div class="settings-desc">Toggle screen capture on and off</div></div></div>'
  + '<div style="display:flex;align-items:center;gap:12px"><input type="text" id="pause-hotkey-input" class="hotkey-input" value="' + (cfg.pause_hotkey || 'ctrl+shift+p') + '" readonly>'
  + '<button class="btn btn-sm" onclick="startHotkeyCapture(\'pause-hotkey-input\')">Record</button>'
  + '<button class="btn btn-sm" style="color:var(--text-muted)" onclick="document.getElementById(\'pause-hotkey-input\').value=\'ctrl+shift+p\'">Reset</button></div>'
  + '<div class="settings-note" style="margin-top:10px">Hotkey changes take effect after restarting ScreenMind.</div></div>'

  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Voice Memo Hotkey</div><div class="settings-desc">Hold to record a voice memo with screenshot</div></div></div>'
  + '<div style="display:flex;align-items:center;gap:12px"><input type="text" id="voice-hotkey-input" class="hotkey-input" value="' + (cfg.voice_hotkey || 'ctrl+shift+v') + '" readonly>'
  + '<button class="btn btn-sm" onclick="startHotkeyCapture(\'voice-hotkey-input\')">Record</button>'
  + '<button class="btn btn-sm" style="color:var(--text-muted)" onclick="document.getElementById(\'voice-hotkey-input\').value=\'ctrl+shift+v\'">Reset</button></div></div>'

  // ── CAPTURE ──
  + _sec('&#128248;', 'Capture')
  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Capture Interval</div><div class="settings-desc">How often to check for screen changes</div></div>'
  + '<span class="settings-value" id="interval-value">' + cfg.capture_interval + 's</span></div>'
  + '<input type="range" id="interval-slider" class="settings-slider" min="10" max="120" step="5" value="' + cfg.capture_interval + '"></div>'

  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Auto-Pause Heavy Apps</div><div class="settings-desc">Pause capture when games or video editors are active</div></div>'
  + _sw('auto-pause-toggle', cfg.auto_pause_heavy_apps) + '</div>'
  + '<div class="settings-input-row"><label class="settings-label">App keywords (comma-separated):</label>'
  + '<input type="text" id="heavy-apps-input" class="settings-text-input" value="' + (cfg.heavy_apps || '') + '" placeholder="game,valorant,blender,obs..."></div></div>'

  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Deferred Analysis</div><div class="settings-desc">Queue screenshots and analyze only when system is idle</div></div>'
  + _sw('defer-toggle', cfg.defer_analysis) + '</div></div>'

  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Capture Active Monitor <span style="background:var(--accent-primary);color:#fff;font-size:10px;padding:2px 6px;border-radius:4px;margin-left:6px;vertical-align:middle">Beta</span></div><div class="settings-desc">Captures the screen with your active window instead of primary monitor. Recommended for multi-monitor setups. Works on Windows, Linux X11, and macOS.</div></div>'
  + _sw('capture-active-monitor', cfg.capture_active_monitor) + '</div></div>'

  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Start at System Startup</div><div class="settings-desc">Automatically launch ScreenMind in background when you log in</div></div>'
  + _sw('startup-toggle', startupStatus.installed) + '</div>'
  + '<div class="settings-note" id="startup-status"></div></div>'

  // ── AI & MODELS ──
  + _sec('&#129504;', 'AI &amp; Models')
  + '<div class="settings-card settings-card-accent" id="model-card"><div class="settings-card-header"><div><div class="settings-title">AI Model</div><div class="settings-desc">Select which Gemma model for analysis and chat</div></div></div>'
  + '<div id="model-list" class="model-list"><div class="spinner" style="margin:12px auto"></div></div></div>'

  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Performance Mode</div><div class="settings-desc">Controls GPU layer offloading for inference</div></div></div>'
  + '<div class="settings-note">Minimal = CPU-only (0 VRAM). Balanced = ~15 layers on GPU (~2GB). Maximum = all layers on GPU (~3GB, fastest).</div>'
  + '<div class="radio-group" id="perf-mode">' + _rp('perf','minimal','Minimal',cfg.performance_mode) + _rp('perf','balanced','Balanced',cfg.performance_mode) + _rp('perf','maximum','Maximum',cfg.performance_mode) + '</div></div>'

  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Context Window</div><div class="settings-desc">Max tokens per request (prompt + image + output)</div></div>'
  + '<span class="settings-value" id="ctx-value">' + (cfg.context_window || 6144) + '</span></div>'
  + '<input type="range" id="ctx-slider" class="settings-slider" min="2048" max="8192" step="1024" value="' + (cfg.context_window || 6144) + '">'
  + '<div class="settings-note">Lower = less VRAM. 6144 fits all features. Increase to 8192 for larger models (E4B). Decrease to 4096 if low on VRAM (may truncate long chat/summaries).</div></div>'

  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">KV Cache Quantization</div><div class="settings-desc">Compress attention cache to save VRAM</div></div>'
  + _sw('kv-cache-quant', cfg.kv_cache_quant === true) + '</div>'
  + '<div class="settings-note">Saves ~200MB VRAM but adds ~10s per inference due to quant/dequant overhead on CPU layers. Only enable if you are running out of VRAM. Disabled by default for faster inference.</div></div>'

  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Flash Attention</div><div class="settings-desc">Optimized attention computation</div></div>'
  + _sw('flash-attention', cfg.flash_attention !== false) + '</div>'
  + '<div class="settings-note">Faster inference and lower VRAM usage. Disable if llama-server fails to start — some older GPUs (pre-Turing) don\'t support it.</div></div>'

  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Analysis Mode</div><div class="settings-desc">How screenshots are analyzed</div></div>'
  + '<div class="radio-group" id="analysis-mode-group">' + _rp('analysis_mode','merged','\u26a1 Accurate (~76s)',cfg.analysis_mode) + _rp('analysis_mode','balanced','\u2696\ufe0f Balanced (~40s)',cfg.analysis_mode) + _rp('analysis_mode','fast','\ud83d\ude80 Fast (~12s)',cfg.analysis_mode) + '</div>'
  + '<div class="settings-note">Accurate: best quality, AI reasons about layout. Balanced: AI thinking without layout. Fast: no thinking, fastest.</div></div>'


  + '<div class="settings-note" style="margin-top:4px;color:#f59e0b;font-size:0.78rem">⚠️ Context Window, KV Cache, and Flash Attention changes require restarting ScreenMind.</div>'

  // ── AUDIO & MEETINGS ──
  + _sec('&#127908;', 'Audio &amp; Meetings')
  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Meeting Transcription</div><div class="settings-desc">Auto-record and summarize meetings</div></div>'
  + _sw('meeting-toggle', cfg.meeting_transcription) + '</div>'
  + '<div class="settings-note">Uses Gemma 4 audio decoding. Requires <code>sounddevice</code>.</div>'
  + '<div class="settings-input-row"><label class="settings-label">Meeting app keywords:</label>'
  + '<input type="text" id="meeting-apps-input" class="settings-text-input" value="' + (cfg.meeting_apps || '') + '" placeholder="zoom,teams,meet,webex,slack..."></div></div>'

  // ── STORAGE ──
  + _sec('&#128451;', 'Storage')
  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Data Retention</div><div class="settings-desc">Auto-delete timeline data older than selected period</div></div></div>'
  + '<div class="settings-note">Data older than the selected period is permanently deleted on every startup.</div>'
  + '<div class="radio-group" id="retention-group">' + _rp('retention','1','1 Day',cfg.retention_days) + _rp('retention','7','7 Days',cfg.retention_days) + _rp('retention','30','30 Days',cfg.retention_days) + _rp('retention','90','90 Days',cfg.retention_days) + _rp('retention','0','Forever',cfg.retention_days) + '</div>'
  + '<div id="storage-estimate" class="settings-note" style="margin-top:8px;font-size:0.82rem"></div></div>'

  // ── MCP ──
  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">MCP Integration</div><div class="settings-desc">Connect screen history to Claude, Cursor, VS Code</div></div></div>'
  + '<div class="settings-note" style="line-height:1.6"><strong>8 tools:</strong> search_screen, search_audio, get_recent_activity, get_activity_by_time, get_daily_summary, get_screenshot, capture_now, get_stats</div>'
  + '<div style="background:rgba(0,0,0,0.3);border-radius:8px;padding:10px 14px;font-family:monospace;font-size:0.75rem;color:var(--text-muted);overflow-x:auto;white-space:pre">{\n  "mcpServers": {\n    "screenmind": {\n      "command": "python",\n      "args": ["-m", "screenmind.mcp_server"]\n    }\n  }\n}</div>'
  + '<div class="settings-note" style="margin-top:8px">See <code>MCP_SETUP.md</code> for full setup instructions.</div></div>'

  // ── INTEGRATIONS ──
  + _sec('&#128279;', 'Integrations')

  // Obsidian
  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Obsidian Export</div><div class="settings-desc">Auto-export daily summaries to your vault</div></div>'
  + _sw('obsidian-enabled', cfg.obsidian_enabled) + '</div>'
  + '<input type="text" id="obsidian-vault-path" class="settings-text-input" value="' + (cfg.obsidian_vault_path || '') + '" placeholder="C:/Users/you/MyVault">'
  + '<div class="settings-note" style="margin-top:6px">Files saved to <code>{vault}/ScreenMind/YYYY-MM-DD.md</code></div></div>'

  // Notion
  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Notion Export</div><div class="settings-desc">Push daily summaries to a Notion database</div></div>'
  + _sw('notion-enabled', cfg.notion_enabled) + '</div>'
  + '<div class="settings-input-row"><label class="settings-label">Notion API Token:</label>'
  + '<input type="password" id="notion-token" class="settings-text-input" value="' + (cfg.notion_token || '') + '" placeholder="secret_..."></div>'
  + '<div class="settings-input-row"><label class="settings-label">Database ID:</label>'
  + '<input type="text" id="notion-database-id" class="settings-text-input" value="' + (cfg.notion_database_id || '') + '" placeholder="abc123..."></div>'
  + '<div style="display:flex;gap:8px;align-items:center;margin-top:8px"><button class="btn btn-sm" onclick="testIntegration(\'notion\')">Test Connection</button><span id="notion-test-result" style="font-size:0.8rem"></span></div></div>'

  // Webhooks (FULL)
  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Webhooks</div><div class="settings-desc">HTTP POST on events (Slack, Discord, IFTTT)</div></div>'
  + _sw('webhook-enabled', cfg.webhook_enabled) + '</div>'
  + '<div class="settings-input-row"><label class="settings-label">Webhook URL (comma-separated for multiple):</label>'
  + '<input type="text" id="webhook-url" class="settings-text-input" value="' + (cfg.webhook_url || '') + '" placeholder="https://hooks.slack.com/..."></div>'
  + '<div class="settings-input-row"><label class="settings-label">Events to fire on:</label>'
  + '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:4px">'
  + ['daily_summary','standup','bookmark','meeting_end','capture_milestone'].map(function(ev) {
      return '<label style="display:flex;align-items:center;gap:4px;font-size:0.82rem;color:var(--text-secondary);cursor:pointer"><input type="checkbox" class="webhook-event-cb" value="' + ev + '" ' + (wh_events.indexOf(ev) >= 0 ? 'checked' : '') + ' style="accent-color:var(--accent)"> ' + ev + '</label>';
    }).join('') + '</div></div>'
  + '<div class="settings-input-row"><label class="settings-label">HMAC Secret (for <code>X-ScreenMind-Signature</code>):</label>'
  + '<input type="text" id="webhook-secret" class="settings-text-input" value="' + (cfg.webhook_secret || '') + '" placeholder="optional secret key"></div>'
  + '<div class="settings-input-row"><label class="settings-label">Custom Headers (one per line: <code>Header: value</code>):</label>'
  + '<textarea id="webhook-headers" class="settings-text-input" rows="2" style="resize:vertical;font-family:monospace;font-size:0.78rem" placeholder="Authorization: Bearer xxx">' + (cfg.webhook_headers || '') + '</textarea></div>'
  + '<div style="display:flex;gap:8px;align-items:center;margin-top:8px"><button class="btn btn-sm" onclick="testIntegration(\'webhook\')">Test Webhook</button><span id="webhook-test-result" style="font-size:0.8rem"></span></div>'
  + '<div style="margin-top:12px"><button id="webhook-log-toggle" class="btn btn-sm btn-ghost" onclick="toggleWebhookLog()" style="margin-bottom:6px">View Delivery Log</button>'
  + '<div id="webhook-log" style="font-size:0.78rem;max-height:200px;overflow-y:auto;display:none"></div></div></div>'

  // Extra webhooks
  + '<div id="extra-hooks-container">'
  + (function() {
    var hooks = cfg.webhook_extra || [];
    var html = '';
    for (var i = 0; i < hooks.length; i++) {
      html += _renderExtraHook(hooks[i], i);
    }
    return html;
  })()
  + '</div>'
  + '<div style="margin-top:8px;margin-bottom:16px"><button class="btn btn-sm btn-ghost" onclick="addExtraHook()" style="display:flex;align-items:center;gap:4px">&#43; Add Webhook</button></div>'

  // ── AUTOMATION ──
  + _sec('&#129302;', 'Automation')
  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Agent System</div><div class="settings-desc">AI agents &amp; Python plugins for automated tasks</div></div>'
  + _sw('agents-enabled', cfg.agents_enabled) + '</div>'
  + '<div class="settings-toggle-row" style="margin-top:8px"><div><div class="settings-toggle-label">Auto-run Python plugins</div><div class="settings-toggle-desc">Skip confirmation before executing</div></div>'
  + _sw('agents-auto-run-python', cfg.agents_auto_run_python) + '</div></div>'

  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Auto-Bookmark</div><div class="settings-desc">Bookmark important moments by keyword</div></div>'
  + _sw('auto-bookmark', cfg.auto_bookmark) + '</div>'
  + '<input type="text" id="auto-bookmark-keywords" class="settings-text-input" value="' + (cfg.auto_bookmark_keywords || '') + '" placeholder="git push,deploy,npm run build">'
  + '<div class="settings-note" style="margin-top:6px">Comma-separated. Matched against screen text and AI summaries.</div></div>'

  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Smart Notifications</div><div class="settings-desc">Distraction alerts and break reminders</div></div>'
  + _sw('smart-notifications', cfg.smart_notifications) + '</div>'
  + '<div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:8px">'
  + '<label style="font-size:0.82rem;color:var(--text-muted);display:flex;align-items:center;gap:6px">Distraction alert <input type="number" id="distraction-minutes" value="' + (cfg.distraction_minutes || 45) + '" min="10" max="180" style="width:55px;padding:4px 8px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:6px;color:var(--text-primary);text-align:center"> min</label>'
  + '<label style="font-size:0.82rem;color:var(--text-muted);display:flex;align-items:center;gap:6px">Break reminder <input type="number" id="break-reminder-minutes" value="' + (cfg.break_reminder_minutes || 90) + '" min="30" max="300" style="width:55px;padding:4px 8px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:6px;color:var(--text-primary);text-align:center"> min</label>'
  + '</div></div>'

  // ── PRIVACY & SECURITY ──
  + _sec('&#128737;', 'Privacy &amp; Security')
  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Sensitive Data Filter</div><div class="settings-desc">Auto-redact PII from captured text before storage</div></div>'
  + _sw('sensitive-filter-enabled', cfg.sensitive_filter_enabled) + '</div>'
  + '<div style="display:flex;flex-direction:column;gap:6px;margin-top:4px">'
  + ['credit_card','ssn','api_key','password','email'].map(function(t) {
      var checked = (cfg.sensitive_filter_types || '').indexOf(t) >= 0 ? 'checked' : '';
      var labels = {credit_card:'Credit Cards', ssn:'SSN/ID Numbers', api_key:'API Keys', password:'Passwords', email:'Email Addresses'};
      return '<label style="display:flex;align-items:center;gap:8px;font-size:0.82rem;color:var(--text-secondary);cursor:pointer"><input type="checkbox" class="filter-type-cb" value="' + t + '" ' + checked + ' style="accent-color:var(--accent)"> ' + labels[t] + '</label>';
    }).join('') + '</div></div>'

  // Dashboard PIN � clear UX
  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Dashboard Lock (PIN)</div><div class="settings-desc">Require a PIN to access the dashboard</div></div></div>'
  + (cfg.dashboard_pin_set
    ? '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;color:#10b981;font-size:0.85rem;font-weight:500">&#10004; PIN is active</div>'
      + '<div style="display:flex;flex-direction:column;gap:10px">'
      + '<div><label class="settings-label">Current PIN:</label><input type="password" id="current-pin" maxlength="6" class="settings-text-input" style="width:140px;text-align:center;letter-spacing:6px" placeholder="&#9679;&#9679;&#9679;&#9679;"></div>'
      + '<div><label class="settings-label">New PIN (leave blank to keep):</label><input type="password" id="new-pin" maxlength="6" class="settings-text-input" style="width:140px;text-align:center;letter-spacing:6px" placeholder="optional"></div>'
      + '<div style="display:flex;gap:8px"><button class="btn btn-sm btn-primary" onclick="changePIN()">Update PIN</button><button class="btn btn-sm" style="color:#ef4444" onclick="removePIN()">Remove PIN</button></div>'
      + '</div>'
    : '<div style="color:var(--text-muted);font-size:0.85rem;margin-bottom:10px">No PIN set &mdash; dashboard is open to anyone on this machine.</div>'
      + '<div><label class="settings-label">Set a 4-6 digit PIN:</label>'
      + '<div style="display:flex;gap:8px;align-items:center;margin-top:4px"><input type="password" id="new-pin" maxlength="6" class="settings-text-input" style="width:140px;text-align:center;letter-spacing:6px" placeholder="e.g. 1234"><button class="btn btn-sm btn-primary" onclick="setPIN()">Set PIN</button></div></div>'
  )
  + '<div id="pin-action-result" style="font-size:0.8rem;margin-top:8px"></div>'
  + '<div style="margin-top:12px;display:flex;align-items:center;gap:8px"><span style="font-size:0.82rem;color:var(--text-muted)">Auto-lock after</span>'
  + '<input type="number" id="dashboard-lock-timeout" value="' + (cfg.dashboard_lock_timeout || 30) + '" min="5" max="480" style="width:55px;padding:4px 8px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:6px;color:var(--text-primary);text-align:center">'
  + '<span style="font-size:0.82rem;color:var(--text-muted)">min of inactivity</span></div></div>'

  + '<div class="settings-card"><div class="settings-card-header"><div><div class="settings-title">Screenshot Encryption</div><div class="settings-desc">Encrypt screenshots at rest (AES-128)</div></div>'
  + _sw('encryption-enabled', cfg.encryption_enabled) + '</div>'
  + '<div class="settings-note">Key stored in OS keyring. Requires <code>pip install cryptography keyring</code>.</div></div>'

  + '</div>';

  // Inject Save button into header bar
  var headerActions = document.getElementById('header-actions');
  if (headerActions) {
    headerActions.innerHTML = '<button class="btn btn-sm" id="save-settings" onclick="saveSettings()" style="padding:6px 18px;font-size:0.82rem;font-weight:600;border-radius:8px;background:rgba(255,255,255,0.06);color:var(--text-muted);border:1px solid rgba(255,255,255,0.08);cursor:default;transition:all 0.25s ease" disabled>Saved</button>';
  }

  // Radio button visual toggle
  el.querySelectorAll('.radio-pill input').forEach(function(radio) {
    radio.addEventListener('change', function() {
      var group = radio.closest('.radio-group');
      group.querySelectorAll('.radio-pill').forEach(function(p) { p.classList.remove('active'); });
      radio.closest('.radio-pill').classList.add('active');
    });
  });
  el.querySelectorAll('#retention-group input').forEach(function(radio) {
    radio.addEventListener('change', updateStorageEstimate);
  });
  var slider = document.getElementById('interval-slider');
  slider.addEventListener('input', function() {
    document.getElementById('interval-value').textContent = slider.value + 's';
  });
  var ctxSlider = document.getElementById('ctx-slider');
  if (ctxSlider) {
    ctxSlider.addEventListener('input', function() {
      document.getElementById('ctx-value').textContent = ctxSlider.value;
    });
  }

  // Track changes for save button state
  setTimeout(function() { _trackSettingsChanges(el); }, 100);

  // Startup toggle (uses separate API, not saveSettings)
  var startupToggle = document.getElementById('startup-toggle');
  if (startupToggle) {
    startupToggle.addEventListener('change', async function() {
      var statusEl = document.getElementById('startup-status');
      try {
        var endpoint = startupToggle.checked ? '/api/startup/install' : '/api/startup/uninstall';
        statusEl.textContent = 'Updating...';
        statusEl.style.color = 'var(--text-muted)';
        var res = await api(endpoint, { method: 'POST' });
        statusEl.textContent = res.message || (res.ok ? 'Done' : 'Failed');
        statusEl.style.color = res.ok ? '#10b981' : '#ef4444';
        setTimeout(function() { statusEl.textContent = ''; }, 3000);
      } catch (e) {
        statusEl.textContent = 'Error: ' + e.message;
        statusEl.style.color = '#ef4444';
        startupToggle.checked = !startupToggle.checked; // revert
      }
    });
  }

  updateStorageEstimate();
  loadModels();
}



async function updateStorageEstimate() {
  const el = document.getElementById('storage-estimate');
  if (!el) return;
  try {
    const data = await api('/api/storage-estimate');
    const selected = document.querySelector('input[name="retention"]:checked');
    const days = selected ? selected.value : '7';
    const est = data.estimates || {};
    const current = data.current_total_mb || 0;
    const perDay = data.avg_mb_per_day || 0;

    if (days === '0') {
      el.innerHTML = `📊 Current storage: <strong>${current} MB</strong> (${data.active_days} days tracked, ~${perDay} MB/day). <em>No auto-cleanup — storage will grow indefinitely.</em>`;
    } else {
      const estimated = est[days] || (perDay * parseInt(days));
      el.innerHTML = `📊 Current: <strong>${current} MB</strong> · Estimated for ${days} days: <strong>~${estimated} MB</strong> (~${perDay} MB/day)`;
    }
  } catch {
    el.textContent = '';
  }
}

async function loadModels() {
  const listEl = document.getElementById('model-list');
  if (!listEl) return;
  try {
    const data = await api('/api/models');
    const models = data.models || [];
    // Sync to global state so overlay stays in sync
    if (typeof _modelState !== 'undefined') _modelState.models = models;

    const isLifecycleActive = typeof _modelState !== 'undefined'
      && ['downloading', 'starting'].includes(_modelState.status);
    const dlModel = typeof _modelState !== 'undefined' && _modelState.download
      ? _modelState.download.model : null;
    // External/unknown model warning card
    let externalCard = '';
    const extModel = typeof _modelState !== 'undefined' ? _modelState.externalModel : null;
    if (extModel && (typeof _modelState === 'undefined' || _modelState.status === 'ready')) {
      externalCard = `
        <div class="model-row" style="border:1px solid rgba(251,191,36,0.3);background:rgba(251,191,36,0.05);margin-bottom:8px">
          <div class="model-info">
            <div class="model-name">\u26a0\ufe0f ${extModel}
              <span class="model-badge" style="background:rgba(251,191,36,0.2);color:#fbbf24">External</span>
            </div>
            <div class="model-meta" style="color:#fbbf24;font-size:0.75rem">Unknown model running on server — may lack vision or audio support</div>
          </div>
        </div>`;
    }

    listEl.innerHTML = externalCard + models.map(m => {
      const isDownloading = isLifecycleActive && dlModel === m.key;

      // Build per-variant rows
      const variantRows = (m.variants || []).map(v => {
        const isThisActive = m.status === 'active' && v.quant === m.active_variant;
        const isThisDownloaded = v.downloaded;

        // Badge
        let vBadge = '';
        if (isThisActive) vBadge = '<span class="model-badge model-active">\u2713 Active</span>';
        else if (isThisDownloaded) vBadge = '<span class="model-badge model-downloaded">Downloaded</span>';

        // Action button
        let vAction = '';
        if (isDownloading || isLifecycleActive) {
          vAction = '<button class="btn-sm" disabled style="opacity:0.4">Busy</button>';
        } else if (isThisActive) {
          vAction = '';
        } else if (isThisDownloaded) {
          vAction = `<button class="btn-sm btn-switch" onclick="settingsSwitchVariant('${m.key}', '${v.quant}')">Switch</button>`;
        } else {
          vAction = `<button class="btn-sm btn-install" onclick="settingsInstallVariant('${m.key}', '${v.quant}')">Download</button>`;
        }

        // Delete button
        let vDelete = '';
        if (isThisActive) {
          vDelete = '<button class="btn-sm" disabled style="opacity:0.3;padding:2px 8px" title="Cannot delete active variant">\ud83d\uddd1</button>';
        } else if (isThisDownloaded && !isLifecycleActive) {
          vDelete = `<button class="btn-sm" onclick="settingsDeleteVariant('${m.key}', '${v.quant}')" title="Delete variant" style="color:#f87171;border-color:rgba(239,68,68,0.3);padding:2px 8px">\ud83d\uddd1</button>`;
        }

        return `
          <div class="model-variant-item ${isThisActive ? 'model-variant-active' : ''}" data-model-key="${m.key}">
            <div class="model-variant-info">
              <span class="model-variant-quant">${v.quant}</span>
              <span class="model-variant-size">${v.file_size}</span>
              ${vBadge}
            </div>
            <div class="model-variant-actions">
              ${vDelete}
              ${vAction}
            </div>
          </div>`;
      }).join('');

      // Download progress
      let progressHtml = '';
      if (isDownloading) {
        const bytes = _modelState.download ? _modelState.download.downloaded_bytes || 0 : 0;
        const bytesStr = typeof _formatBytes === 'function' ? _formatBytes(bytes) : bytes + ' B';
        progressHtml = `<div style="padding:4px 12px;font-size:0.75rem;color:var(--accent)"><span data-progress-bytes>\ud83d\udce6 ${bytesStr}</span> <button class="btn-sm" onclick="hubCancelDownload()" style="color:#f87171;border-color:rgba(239,68,68,0.3);margin-left:6px">Cancel</button></div>`;
      }

      return `
        <div class="model-row" data-model-key="${m.key}">
          <div class="model-info">
            <div class="model-name">${m.name}
              ${isDownloading ? '<span class="model-badge" style="background:rgba(139,92,246,0.15);color:var(--accent)">Downloading...</span>' : ''}
            </div>
            <div class="model-meta">${m.size} params \u00b7 ${m.vram} VRAM \u00b7 ${m.quality}</div>
          </div>
        </div>
        ${variantRows}
        ${progressHtml}`;
    }).join('');
  } catch (e) {
    listEl.innerHTML = '<div class="settings-note">\u26a0\ufe0f Could not load models.</div>';
  }
}



window.settingsInstallVariant = async function(key, quant) {
  if (typeof _confirmAudioLoss === 'function' && !_confirmAudioLoss(key)) return;
  if (!confirm(`Download ${key} (${quant})?\nThis will download the model. Continue?`)) return;
  try {
    const res = await fetch('/api/models/pull', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, quant }),
    });
    if (res.ok) {
      showToast('Download started. Check Model Hub for progress.', 'info');
    } else {
      const j = await res.json().catch(() => ({}));
      showToast(j.error || 'Download failed to start', 'warning');
    }
    loadModels();
  } catch (e) {
    showToast('Failed to start download: ' + e.message, 'warning');
    loadModels();
  }
};

window.settingsSwitchVariant = async function(key, quant) {
  if (typeof _confirmAudioLoss === 'function' && !_confirmAudioLoss(key)) return;
  if (!confirm('Switching requires a server restart. Continue?')) return;
  try {
    // Save variant preference
    await fetch('/api/models/variant', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, quant }),
    });
    // Switch to this model if it's a different model
    const activeModel = typeof _modelState !== 'undefined' ? _modelState.activeModel : null;
    if (activeModel !== key) {
      await fetch('/api/models/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key }),
      });
    }
    showToast(`Switching to ${key} (${quant})...`, 'info');
    loadModels();
  } catch (e) {
    showToast('Failed to switch: ' + e.message, 'warning');
  }
};

window.settingsDeleteVariant = async function(key, quant) {
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
      loadModels();
    } else {
      showToast(j.error || 'Delete failed', 'warning');
    }
  } catch (e) {
    showToast('Delete failed: ' + e.message, 'warning');
  }
};
// Hotkey capture function
window.startHotkeyCapture = function(inputId) {
  var el = document.getElementById(inputId);
  if (!el) return;
  el.value = 'Press keys...';
  el.style.borderColor = 'var(--accent)';
  el.style.boxShadow = '0 0 0 3px rgba(139,92,246,0.2)';

  function handler(e) {
    e.preventDefault();
    e.stopPropagation();
    // Ignore lone modifier keys
    if (['Control','Shift','Alt','Meta'].includes(e.key)) return;

    var parts = [];
    if (e.ctrlKey) parts.push('ctrl');
    if (e.shiftKey) parts.push('shift');
    if (e.altKey) parts.push('alt');
    parts.push(e.key.toLowerCase());

    el.value = parts.join('+');
    el.style.borderColor = '';
    el.style.boxShadow = '';
    document.removeEventListener('keydown', handler, true);
  }
  document.addEventListener('keydown', handler, true);
};

window.saveSettings = async function() {
  var perf = document.querySelector('input[name="perf"]:checked');
  var retention = document.querySelector('input[name="retention"]:checked');

  var body = {
    performance_mode: perf ? perf.value : 'balanced',
    context_window: parseInt(document.getElementById('ctx-slider').value) || 6144,
    kv_cache_quant: document.getElementById('kv-cache-quant').checked,
    flash_attention: document.getElementById('flash-attention').checked,
    analysis_mode: (document.querySelector('input[name="analysis_mode"]:checked') || {}).value || 'merged',
    auto_pause_heavy_apps: document.getElementById('auto-pause-toggle').checked,
    heavy_apps: document.getElementById('heavy-apps-input').value,
    defer_analysis: document.getElementById('defer-toggle').checked,
    capture_interval: parseInt(document.getElementById('interval-slider').value),
    capture_active_monitor: document.getElementById('capture-active-monitor').checked,
    meeting_transcription: document.getElementById('meeting-toggle').checked,
    meeting_apps: document.getElementById('meeting-apps-input').value,
    retention_days: retention ? parseInt(retention.value) : 7,
    // Integrations
    obsidian_enabled: (document.getElementById('obsidian-enabled') || {}).checked || false,
    obsidian_vault_path: (document.getElementById('obsidian-vault-path') || {}).value || '',
    notion_enabled: (document.getElementById('notion-enabled') || {}).checked || false,
    notion_token: (document.getElementById('notion-token') || {}).value || '',
    notion_database_id: (document.getElementById('notion-database-id') || {}).value || '',
    webhook_enabled: (document.getElementById('webhook-enabled') || {}).checked || false,
    webhook_url: (document.getElementById('webhook-url') || {}).value || '',
    webhook_events: (function() { var evts=[]; document.querySelectorAll('.webhook-event-cb:checked').forEach(function(cb){evts.push(cb.value)}); return evts.join(','); })(),
    webhook_secret: (document.getElementById('webhook-secret') || {}).value || '',
    webhook_headers: (document.getElementById('webhook-headers') || {}).value || '',
    webhook_extra: _collectExtraHooks(),
    // Automation
    agents_enabled: document.getElementById('agents-enabled').checked,
    agents_auto_run_python: document.getElementById('agents-auto-run-python').checked,
    auto_bookmark: document.getElementById('auto-bookmark').checked,
    auto_bookmark_keywords: document.getElementById('auto-bookmark-keywords').value,
    smart_notifications: document.getElementById('smart-notifications').checked,
    distraction_minutes: parseInt(document.getElementById('distraction-minutes').value) || 45,
    break_reminder_minutes: parseInt(document.getElementById('break-reminder-minutes').value) || 90,
    // Privacy
    sensitive_filter_enabled: document.getElementById('sensitive-filter-enabled').checked,
    sensitive_filter_types: (function() {
      var types = [];
      document.querySelectorAll('.filter-type-cb:checked').forEach(function(cb) { types.push(cb.value); });
      return types.join(',');
    })(),
    dashboard_lock_timeout: parseInt(document.getElementById('dashboard-lock-timeout').value) || 30,
    encryption_enabled: document.getElementById('encryption-enabled').checked,
    // Hotkeys
    bookmark_hotkey: document.getElementById('bookmark-hotkey-input').value,
    pause_hotkey: document.getElementById('pause-hotkey-input').value,
    voice_hotkey: document.getElementById('voice-hotkey-input').value,
  };
  try {
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    showToast('Settings saved', 'success');
    _markSettingsSaved();
  } catch {
    showToast('Failed to save settings', 'warning');
  }
};

// PIN management functions
window.setPIN = async function() {
  var pin = document.getElementById('new-pin').value;
  if (!pin || pin.length < 4) { showToast('PIN must be 4-6 digits', 'warning'); return; }
  var r = await fetch('/api/auth/set-pin', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({pin:pin}) }).then(r=>r.json());
  if (r.ok) { showToast('PIN set! Dashboard is now locked.', 'success'); navigate('settings'); }
  else { showToast(r.error || 'Failed', 'warning'); }
};
window.changePIN = async function() {
  var current = document.getElementById('current-pin').value;
  var newPin = document.getElementById('new-pin').value;
  if (!newPin || newPin.length < 4) { showToast('New PIN must be 4-6 digits', 'warning'); return; }
  var r = await fetch('/api/auth/set-pin', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({pin:newPin, current_pin:current}) }).then(r=>r.json());
  if (r.ok) { showToast('PIN changed!', 'success'); navigate('settings'); }
  else { showToast(r.error || 'Current PIN incorrect', 'warning'); }
};
window.removePIN = async function() {
  if (!confirm('Remove PIN? Dashboard will be accessible without authentication.')) return;
  var current = document.getElementById('current-pin').value;
  var r = await fetch('/api/auth/set-pin', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({pin:'', current_pin:current}) }).then(r=>r.json());
  if (r.ok) { showToast('PIN removed', 'success'); navigate('settings'); }
  else { showToast(r.error || 'Current PIN incorrect', 'warning'); }
};
window.testIntegration = async function(type) {
  var resultEl = document.getElementById(type === 'notion' ? 'notion-test-result' : 'webhook-test-result');
  resultEl.innerHTML = '<span style="color:var(--text-muted)">Testing...</span>';

  var payload = { type: type };
  if (type === 'notion') {
    payload.token = document.getElementById('notion-token').value;
    payload.database_id = document.getElementById('notion-database-id').value;
  } else {
    payload.url = document.getElementById('webhook-url').value;
    payload.secret = document.getElementById('webhook-secret').value;
    payload.headers = document.getElementById('webhook-headers').value;
  }

  try {
    var resp = await fetch('/api/integrations/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    var result = await resp.json();
    if (result.ok) {
      resultEl.innerHTML = '<span style="color:#10b981">✅ Connection successful' + (result.database_title ? ` — ${result.database_title}` : '') + '</span>';
    } else {
      resultEl.innerHTML = '<span style="color:#f59e0b">❌ ' + (result.error || 'Failed') + '</span>';
    }
  } catch (e) {
    resultEl.innerHTML = '<span style="color:#ef4444">❌ ' + e.message + '</span>';
  }
};

window.loadWebhookLog = async function() {
  var logEl = document.getElementById('webhook-log');
  if (!logEl) return;
  logEl.innerHTML = '<span style="color:var(--text-muted)">Loading...</span>';
  try {
    var resp = await api('/api/webhooks/log');
    var deliveries = resp.deliveries || [];
    if (deliveries.length === 0) {
      logEl.innerHTML = '<span style="color:var(--text-muted)">No deliveries yet. Enable webhooks and trigger an event.</span>';
      return;
    }
    var rows = deliveries.map(function(d) {
      var icon = d.status === 'ok' ? '✅' : '❌';
      var statusColor = d.status === 'ok' ? '#10b981' : '#ef4444';
      var time = d.timestamp ? d.timestamp.replace('T', ' ').replace('Z', '') : '';
      time = time.substring(5, 16); // MM-DD HH:MM
      var retry = d.attempt > 1 ? ' <span style="color:#f59e0b">(retry)</span>' : '';
      var hookLabel = d.hook_name ? '<span style="color:' + (d.hook_name === 'default' ? 'var(--text-muted)' : 'var(--accent)') + ';font-size:0.72rem">' + d.hook_name + '</span>' : '';
      var err = d.error ? '<br><span style="color:#ef4444;font-size:0.72rem">' + d.error.substring(0, 60) + '</span>' : '';
      return '<tr style="border-bottom:1px solid rgba(255,255,255,0.04)">' +
        '<td style="padding:4px 8px">' + icon + '</td>' +
        '<td style="padding:4px 8px;color:var(--text-muted)">' + time + '</td>' +
        '<td style="padding:4px 8px"><code style="font-size:0.75rem">' + d.event + '</code>' + retry + '</td>' +
        '<td style="padding:4px 8px">' + hookLabel + '</td>' +
        '<td style="padding:4px 8px;color:var(--text-muted);max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + d.url + '</td>' +
        '<td style="padding:4px 8px">' + (d.status_code || '') + err + '</td></tr>';
    }).join('');
    logEl.innerHTML = '<table style="width:100%;border-collapse:collapse"><thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1)"><th style="padding:4px 8px;text-align:left;font-size:0.72rem;color:var(--text-muted)"></th><th style="text-align:left;font-size:0.72rem;color:var(--text-muted);padding:4px 8px">Time</th><th style="text-align:left;font-size:0.72rem;color:var(--text-muted);padding:4px 8px">Event</th><th style="text-align:left;font-size:0.72rem;color:var(--text-muted);padding:4px 8px">Hook</th><th style="text-align:left;font-size:0.72rem;color:var(--text-muted);padding:4px 8px">URL</th><th style="text-align:left;font-size:0.72rem;color:var(--text-muted);padding:4px 8px">Status</th></tr></thead><tbody id="log-tbody">' + rows + '</tbody></table>';
  } catch (e) {
    logEl.innerHTML = '<span style="color:#ef4444">Failed to load: ' + e.message + '</span>';
  }
};

window.toggleWebhookLog = function() {
  var logEl = document.getElementById('webhook-log');
  var btn = document.getElementById('webhook-log-toggle');
  if (!logEl || !btn) return;
  if (logEl.style.display === 'none' || !logEl.style.display) {
    logEl.style.display = 'block';
    btn.textContent = 'Close Delivery Log';
    loadWebhookLog();
  } else {
    logEl.style.display = 'none';
    logEl.innerHTML = '';
    btn.textContent = 'View Delivery Log';
  }
};

// ── Extra Webhook Hooks ────────────────────────────────────────────────

var _extraHookCounter = 0;

function _renderExtraHook(hook, idx) {
  var id = 'extra-hook-' + idx;
  var events = (hook.events || '').split(',');
  var allEvents = ['daily_summary','standup','bookmark','meeting_end','capture_milestone'];
  return '<div class="settings-card extra-hook-card" data-hookidx="' + idx + '" style="border-left:3px solid var(--accent);margin-top:8px">'
    + '<div class="settings-card-header"><div>'
    + '<div class="settings-title" style="font-size:0.9rem">🔗 ' + (hook.name || 'unnamed') + '</div>'
    + '<div class="settings-desc" style="font-size:0.75rem">Extra webhook profile</div></div>'
    + '<div style="display:flex;gap:8px;align-items:center">'
    + '<label style="font-size:0.78rem;color:var(--text-secondary);display:flex;align-items:center;gap:4px"><input type="checkbox" class="ehook-enabled" ' + (hook.enabled !== false ? 'checked' : '') + ' style="accent-color:var(--accent)"> Enabled</label>'
    + '<button class="btn btn-sm" style="color:#ef4444;font-size:0.75rem" onclick="removeExtraHook(' + idx + ')">✕</button>'
    + '</div></div>'
    + '<input type="hidden" class="ehook-name" value="' + (hook.name || '') + '">'
    + '<div class="settings-input-row"><label class="settings-label" style="font-size:0.8rem">URL:</label>'
    + '<input type="text" class="settings-text-input ehook-url" value="' + (hook.url || '') + '" placeholder="https://..."></div>'
    + '<div class="settings-input-row"><label class="settings-label" style="font-size:0.8rem">Events:</label>'
    + '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:2px">'
    + allEvents.map(function(ev) {
        return '<label style="display:flex;align-items:center;gap:3px;font-size:0.78rem;color:var(--text-secondary);cursor:pointer"><input type="checkbox" class="ehook-event" value="' + ev + '" ' + (events.indexOf(ev) >= 0 ? 'checked' : '') + ' style="accent-color:var(--accent)"> ' + ev + '</label>';
      }).join('')
    + '</div></div>'
    + '<div class="settings-input-row"><label class="settings-label" style="font-size:0.8rem">HMAC Secret:</label>'
    + '<input type="text" class="settings-text-input ehook-secret" value="' + (hook.secret || '') + '" placeholder="optional"></div>'
    + '<div class="settings-input-row"><label class="settings-label" style="font-size:0.8rem">Custom Headers:</label>'
    + '<textarea class="settings-text-input ehook-headers" rows="1" style="resize:vertical;font-family:monospace;font-size:0.75rem" placeholder="Key: Value">' + (hook.headers || '') + '</textarea></div>'
    + '<div style="display:flex;gap:8px;align-items:center;margin-top:8px"><button class="btn btn-sm" onclick="testExtraHook(' + idx + ')">Test Webhook</button><span id="ehook-test-result-' + idx + '" style="font-size:0.8rem"></span></div>'
    + '</div>';
}

function _collectExtraHooks() {
  var hooks = [];
  var cards = document.querySelectorAll('.extra-hook-card');
  cards.forEach(function(card) {
    var evts = [];
    card.querySelectorAll('.ehook-event:checked').forEach(function(cb) { evts.push(cb.value); });
    hooks.push({
      name: (card.querySelector('.ehook-name') || {}).value || 'unnamed',
      url: (card.querySelector('.ehook-url') || {}).value || '',
      events: evts.join(','),
      secret: (card.querySelector('.ehook-secret') || {}).value || '',
      headers: (card.querySelector('.ehook-headers') || {}).value || '',
      enabled: (card.querySelector('.ehook-enabled') || {}).checked !== false,
    });
  });
  return hooks;
}

window.addExtraHook = function() {
  _showHookNameModal(function(name) {
    name = name.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '');
    if (!name) { showToast('Invalid name. Use letters, numbers, hyphens, underscores.', 'warning'); return; }
    // Check for duplicate names
    var existing = document.querySelectorAll('.ehook-name');
    for (var i = 0; i < existing.length; i++) {
      if (existing[i].value === name) { showToast('A hook named "' + name + '" already exists.', 'warning'); return; }
    }
    var container = document.getElementById('extra-hooks-container');
    if (!container) return;
    var idx = _extraHookCounter++;
    var html = _renderExtraHook({ name: name, url: '', events: 'daily_summary,standup,bookmark', secret: '', headers: '', enabled: true }, idx);
    container.insertAdjacentHTML('beforeend', html);
  });
};

window.removeExtraHook = function(idx) {
  var card = document.querySelector('.extra-hook-card[data-hookidx="' + idx + '"]');
  if (!card) return;
  var hookName = (card.querySelector('.ehook-name') || {}).value || 'this webhook';
  _showConfirmModal('Remove "' + hookName + '"?', 'This webhook profile will be deleted. Save settings to apply.', function() {
    card.remove();
  });
};

function _showConfirmModal(title, message, onConfirm) {
  var old = document.getElementById('confirm-modal');
  if (old) old.remove();

  var overlay = document.createElement('div');
  overlay.id = 'confirm-modal';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);animation:fadeIn 0.15s ease-out';

  var modal = document.createElement('div');
  modal.style.cssText = 'background:var(--bg-secondary,#1a1a2e);border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;min-width:320px;max-width:400px;box-shadow:0 20px 60px rgba(0,0,0,0.5)';

  modal.innerHTML = '<div style="font-size:1rem;font-weight:600;color:var(--text-primary);margin-bottom:4px">' + title + '</div>'
    + '<div style="font-size:0.82rem;color:var(--text-muted);margin-bottom:20px">' + message + '</div>'
    + '<div style="display:flex;gap:8px;justify-content:flex-end">'
    + '<button id="confirm-cancel" class="btn btn-sm btn-ghost" style="padding:8px 16px">Cancel</button>'
    + '<button id="confirm-yes" class="btn btn-sm" style="padding:8px 16px;background:#ef4444;color:#fff;border:none">Remove</button>'
    + '</div>';

  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  function close() { overlay.remove(); }
  document.getElementById('confirm-cancel').onclick = close;
  document.getElementById('confirm-yes').onclick = function() { close(); onConfirm(); };
  overlay.addEventListener('click', function(e) { if (e.target === overlay) close(); });
  document.addEventListener('keydown', function handler(e) {
    if (e.key === 'Escape') { close(); document.removeEventListener('keydown', handler); }
  });
}

window.testExtraHook = async function(idx) {
  var card = document.querySelector('.extra-hook-card[data-hookidx="' + idx + '"]');
  if (!card) return;
  var url = (card.querySelector('.ehook-url') || {}).value;
  var secret = (card.querySelector('.ehook-secret') || {}).value || '';
  var headers = (card.querySelector('.ehook-headers') || {}).value || '';
  var resultEl = document.getElementById('ehook-test-result-' + idx);
  if (!url) { if (resultEl) resultEl.innerHTML = '<span style="color:#f59e0b">Enter a URL first</span>'; return; }
  if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-muted)">Testing...</span>';
  try {
    var resp = await fetch('/api/integrations/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'webhook', url: url, secret: secret, headers: headers }),
    });
    var result = await resp.json();
    if (result.ok) {
      resultEl.innerHTML = '<span style="color:#10b981">✅ Connection successful</span>';
    } else {
      resultEl.innerHTML = '<span style="color:#f59e0b">❌ ' + (result.error || 'Failed') + '</span>';
    }
  } catch (e) {
    resultEl.innerHTML = '<span style="color:#ef4444">❌ ' + e.message + '</span>';
  }
};

// ── Themed Modal for Hook Name ─────────────────────────────────────────

function _showHookNameModal(onSubmit) {
  // Remove any existing modal
  var old = document.getElementById('hook-name-modal');
  if (old) old.remove();

  var overlay = document.createElement('div');
  overlay.id = 'hook-name-modal';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);animation:fadeIn 0.15s ease-out';

  var modal = document.createElement('div');
  modal.style.cssText = 'background:var(--bg-secondary,#1a1a2e);border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;min-width:340px;max-width:400px;box-shadow:0 20px 60px rgba(0,0,0,0.5)';

  modal.innerHTML = '<div style="font-size:1rem;font-weight:600;color:var(--text-primary);margin-bottom:4px">Add Webhook</div>'
    + '<div style="font-size:0.8rem;color:var(--text-muted);margin-bottom:16px">Give this webhook a name for easy identification.</div>'
    + '<input id="hook-name-input" type="text" class="settings-text-input" placeholder="e.g. discord, slack, alerts" style="width:100%;box-sizing:border-box;font-size:0.85rem;padding:10px 12px" autofocus>'
    + '<div id="hook-name-error" style="font-size:0.75rem;color:#ef4444;margin-top:6px;min-height:18px"></div>'
    + '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">'
    + '<button id="hook-name-cancel" class="btn btn-sm btn-ghost" style="padding:8px 16px">Cancel</button>'
    + '<button id="hook-name-submit" class="btn btn-sm btn-primary" style="padding:8px 16px">Add</button>'
    + '</div>';

  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  var input = document.getElementById('hook-name-input');
  var errorEl = document.getElementById('hook-name-error');
  setTimeout(function() { input.focus(); }, 50);

  function close() { overlay.remove(); }

  function submit() {
    var val = input.value.trim();
    if (!val) { errorEl.textContent = 'Name is required'; input.focus(); return; }
    var cleaned = val.toLowerCase().replace(/[^a-z0-9_-]/g, '');
    if (!cleaned) { errorEl.textContent = 'Use only letters, numbers, hyphens, underscores'; input.focus(); return; }
    close();
    onSubmit(cleaned);
  }

  document.getElementById('hook-name-cancel').onclick = close;
  document.getElementById('hook-name-submit').onclick = submit;
  overlay.addEventListener('click', function(e) { if (e.target === overlay) close(); });
  input.addEventListener('keydown', function(e) {
    errorEl.textContent = '';
    if (e.key === 'Enter') { e.preventDefault(); submit(); }
    if (e.key === 'Escape') close();
  });
}

// ── Settings Change Tracking ──────────────────────────────────────────

var _settingsSnapshot = '';

function _captureSettingsSnapshot(container) {
  // Capture current state of all form inputs as a string for comparison
  var parts = [];
  container.querySelectorAll('input, textarea, select').forEach(function(el) {
    if (el.type === 'checkbox' || el.type === 'radio') {
      parts.push(el.id + ':' + el.checked);
    } else {
      parts.push(el.id + ':' + el.value);
    }
  });
  return parts.join('|');
}

function _getCurrentSettingsState(container) {
  return _captureSettingsSnapshot(container);
}

function _markSettingsUnsaved() {
  var btn = document.getElementById('save-settings');
  if (!btn) return;
  btn.disabled = false;
  btn.textContent = 'Save';
  btn.style.background = '#10b981';
  btn.style.color = '#fff';
  btn.style.border = '1px solid #10b981';
  btn.style.cursor = 'pointer';
  btn.style.boxShadow = '0 0 12px rgba(16,185,129,0.3)';
}

function _markSettingsSaved() {
  var btn = document.getElementById('save-settings');
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = 'Saved';
  btn.style.background = 'rgba(255,255,255,0.06)';
  btn.style.color = 'var(--text-muted)';
  btn.style.border = '1px solid rgba(255,255,255,0.08)';
  btn.style.cursor = 'default';
  btn.style.boxShadow = 'none';
  // Update snapshot to current state
  var container = document.querySelector('.settings-grid');
  if (container) _settingsSnapshot = _captureSettingsSnapshot(container);
}

function _trackSettingsChanges(container) {
  // Capture initial snapshot
  _settingsSnapshot = _captureSettingsSnapshot(container);

  // Listen for any input change
  container.addEventListener('input', function() {
    var current = _getCurrentSettingsState(container);
    if (current !== _settingsSnapshot) {
      _markSettingsUnsaved();
    } else {
      _markSettingsSaved();
    }
  });
  container.addEventListener('change', function() {
    var current = _getCurrentSettingsState(container);
    if (current !== _settingsSnapshot) {
      _markSettingsUnsaved();
    } else {
      _markSettingsSaved();
    }
  });
}

// Clean up header-actions when navigating away from settings
document.addEventListener('click', function(e) {
  var navItem = e.target.closest('.nav-item');
  if (navItem && navItem.dataset.view !== 'settings') {
    var ha = document.getElementById('header-actions');
    if (ha) ha.innerHTML = '';
  }
});
window.addEventListener('hashchange', function() {
  var view = window.location.hash.slice(1);
  if (view && view !== 'settings') {
    var ha = document.getElementById('header-actions');
    if (ha) ha.innerHTML = '';
  }
});

// ── Init ──────────────────────────────────────────────────
function _initApp() {
  const initialView = window.location.hash.slice(1) || 'timeline';
  requestAnimationFrame(() => {
    const activeBtn = $(`[data-view="${initialView}"]`);
    if (activeBtn) moveIndicator(activeBtn);
  });
  navigate(initialView);
  pollStatus();
  _setPollInterval(15000); // adaptive: core.js switches to 5s during downloads
}

window.shutdownScreenMind = async function() {
  if (!confirm('Stop ScreenMind?\n\nThe background process and API server will shut down.\nYou can restart it from the desktop shortcut or terminal.')) return;
  var btn = document.getElementById('shutdown-btn');
  btn.textContent = 'Stopping...';
  btn.disabled = true;
  try {
    await api('/api/shutdown', { method: 'POST' });
  } catch (e) {
    // Expected — server dies before response completes
  }
  document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;color:var(--text-muted);font-size:1.1rem">ScreenMind stopped.</div>';
};

// Wait for auth check before initializing app
_checkAuth().then(function() {
  if (!_dashboardLocked) {
    _initApp();
  }
});
