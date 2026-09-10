// ── Agents Tab ─────────────────────────────────────────────────────
async function renderAgents(el) {
  el.innerHTML = '<div class="spinner"></div>';
  let data;
  try {
    data = await api('/api/agents');
  } catch {
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">Cannot load agents</div></div>';
    return;
  }

  var agents = data.agents || [];
  var html = '';

  // Header with create buttons
  html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">';
  html += '<div style="color:var(--text-muted);font-size:0.85rem">' + agents.length + ' agent(s) installed</div>';
  html += '<div style="display:flex;gap:8px">';
  html += '<button class="btn" onclick="createAgent(\'markdown\')" style="font-size:0.82rem;padding:6px 14px">🤖 New AI Agent</button>';
  html += '<button class="btn" onclick="createAgent(\'python\')" style="font-size:0.82rem;padding:6px 14px">🐍 New Python Plugin</button>';
  html += '<button class="btn" onclick="document.getElementById(\'import-agent-file\').click()" style="font-size:0.82rem;padding:6px 14px">📥 Import .py</button>';
  html += '<input type="file" id="import-agent-file" accept=".py,.md" style="display:none" onchange="importAgentFile(this)">';
  html += '</div></div>';

  if (agents.length === 0) {
    html += '<div class="empty-state"><div class="empty-icon">🤖</div><div class="empty-title">No agents installed</div>';
    html += '<div class="empty-desc">Create an AI agent or Python plugin to automate tasks with your screen data.</div></div>';
  } else {
    html += '<div class="settings-grid">';
    agents.forEach(function(a) {
      var typeBadge = a.type === 'python'
        ? '<span style="font-size:0.7rem;background:rgba(16,185,129,0.15);color:#10b981;padding:2px 8px;border-radius:10px;font-weight:500">🐍 Python</span>'
        : '<span style="font-size:0.7rem;background:rgba(139,92,246,0.15);color:#8b5cf6;padding:2px 8px;border-radius:10px;font-weight:500">🤖 AI</span>';

      var statusDot = '';
      var lastRunInfo = '';
      if (a.last_run) {
        var icon = a.last_run.status === 'ok' ? '✅' : a.last_run.status === 'needs_approval' ? '🔒' : '❌';
        statusDot = icon;
        var t = a.last_run.timestamp || '';
        lastRunInfo = '<div style="font-size:0.75rem;color:var(--text-muted);margin-top:6px">' + icon + ' Last: ' + t.replace('T',' ').substring(0,16) + ' (' + a.last_run.duration + 's)</div>';
        if (a.last_run.output && a.last_run.status === 'ok') {
          lastRunInfo += '<div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px;max-height:60px;overflow:hidden;opacity:0.7">' + a.last_run.output.substring(0, 150).replace(/</g,'&lt;') + '...</div>';
        }
      }

      var enabledStyle = a.enabled ? '' : 'opacity:0.5;';

      // Data source badges
      var dataBadges = '';
      var dataStr = (a.data || '').trim();
      if (dataStr && a.type !== 'python') {
        var dataIcons = {
          'timeline': '📋',
          'urls': '🔗',
          'apps': '📱',
          'meetings': '🎤',
          'mood': '😊'
        };
        dataStr.split(',').forEach(function(d) {
          d = d.trim().toLowerCase();
          if (d && dataIcons[d]) {
            dataBadges += '<span style="font-size:0.72rem;background:rgba(59,130,246,0.12);color:#60a5fa;padding:2px 7px;border-radius:6px;margin-right:4px">' + dataIcons[d] + ' ' + d + '</span>';
          }
        });
      } else if (a.type === 'python') {
        dataBadges = '<span style="font-size:0.72rem;background:rgba(16,185,129,0.12);color:#34d399;padding:2px 7px;border-radius:6px">⚡ SDK</span>';
      }

      // Model requirement badge
      var modelBadge = '';
      var modelReq = parseInt(a.model_requirement || '0');
      if (modelReq > 0) {
        modelBadge = '<span style="font-size:0.72rem;background:rgba(245,158,11,0.15);color:#f59e0b;padding:2px 7px;border-radius:6px;margin-left:4px" title="Needs ' + modelReq + '+ context tokens">⚠️ ' + Math.round(modelReq/1024) + 'k ctx</span>';
      }

      // Output destinations
      var outputDest = a.output || 'local';
      var destIcons = outputDest.split(',').map(function(d) {
        d = d.trim();
        if (d === 'obsidian') return '📒 Obsidian';
        if (d === 'webhook') return '🪝 Webhook';
        if (d === 'notion') return '📝 Notion';
        return '💾 Local';
      }).join(' + ');

      html += '<div class="settings-card" style="' + enabledStyle + '">';

      // Row 1: Name + type badge + toggle
      html += '<div style="display:flex;justify-content:space-between;align-items:flex-start">';
      html += '<div style="flex:1;min-width:0">';
      html += '<div style="font-weight:600;color:var(--text);margin-bottom:4px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">';
      html += '<span>' + (a.name || a.filepath) + '</span> ' + typeBadge + modelBadge;
      html += '</div>';
      html += '<div style="font-size:0.8rem;color:var(--text-muted);margin-bottom:6px">' + (a.description || 'No description') + '</div>';

      // Row 2: Schedule + output + data badges
      html += '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">';
      html += '<span style="font-size:0.75rem;color:var(--text-muted)">⏱️ ' + (a.schedule || 'every 6h') + '</span>';
      html += '<span style="font-size:0.75rem;color:var(--text-muted)">→ ' + destIcons + '</span>';
      if (dataBadges) {
        html += '<span style="font-size:0.75rem;color:var(--text-muted);margin-left:4px">│</span> ' + dataBadges;
      }
      html += '</div>';

      // Row 3: Last run info
      html += lastRunInfo;
      html += '</div>';

      // Toggle
      html += '<label class="settings-toggle" style="margin:0"><input type="checkbox" ' + (a.enabled ? 'checked' : '') + ' onchange="toggleAgent(\'' + (a.slug || a.name) + '\', this.checked)"><span></span></label>';
      html += '</div>';

      // Action buttons
      html += '<div style="display:flex;gap:6px;margin-top:10px;border-top:1px solid rgba(255,255,255,0.06);padding-top:8px">';
      html += '<button class="btn" style="font-size:0.75rem;padding:4px 10px" onclick="runAgentNow(\'' + (a.slug || a.name) + '\')">▶ Run Now</button>';
      html += '<button class="btn" style="font-size:0.75rem;padding:4px 10px" onclick="editAgent(\'' + (a.slug || a.name) + '\')">✏️ Edit</button>';
      html += '<button class="btn" style="font-size:0.75rem;padding:4px 10px" onclick="viewAgentOutputs(\'' + (a.slug || a.name) + '\')">📄 Outputs</button>';
      if (a.type === 'python') {
        html += '<button class="btn" style="font-size:0.75rem;padding:4px 10px" onclick="openAgentInEditor(\'' + (a.slug || a.name) + '\')">📂 Open in Editor</button>';
      }
      if (a.type === 'python' && a.last_run && a.last_run.status === 'needs_approval') {
        html += '<button class="btn" style="font-size:0.75rem;padding:4px 10px;background:rgba(16,185,129,0.15);color:#10b981" onclick="approveAgent(\'' + (a.slug || a.name) + '\')">✅ Approve & Run</button>';
      }
      html += '<button class="btn" style="font-size:0.75rem;padding:4px 10px;margin-left:auto;color:#ef4444" onclick="confirmDeleteAgent(\'' + (a.slug || a.name) + '\', \'' + (a.name || a.slug).replace(/'/g,'') + '\')">🗑️ Delete</button>';
      html += '</div></div>';
    });
    html += '</div>';
  }

  // Agent Run Log
  html += '<div style="margin-top:28px;padding-top:16px;border-top:1px solid rgba(255,255,255,0.06)">';
  html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">';
  html += '<div style="font-weight:600;color:var(--text)">\ud83d\udccb Agent Run Log</div>';
  html += '<button class="btn" style="font-size:0.75rem;padding:4px 10px" onclick="navigate(\'agents\')">🔄 Refresh</button>';
  html += '</div>';
  html += '<div id="agent-log">Loading...</div>';
  html += '</div>';

  // Create Agent Inline Form (hidden)
  html += '<div id="create-agent-form" style="display:none;background:#111827;border:1px solid rgba(139,92,246,0.3);border-radius:12px;padding:16px;margin-bottom:16px">';
  html += '<div style="font-weight:600;color:var(--text-primary);margin-bottom:10px">Create New Agent</div>';
  html += '<div style="display:flex;gap:10px;align-items:center">';
  html += '<input type="text" id="new-agent-name" placeholder="agent-name (lowercase, no spaces)" style="flex:1;padding:8px 12px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);border-radius:8px;color:var(--text-primary);font-size:0.85rem" autocomplete="off">';
  html += '<button class="btn btn-primary" style="font-size:0.82rem;padding:6px 16px" id="confirm-create-agent">Create</button>';
  html += '<button class="btn" style="font-size:0.82rem;padding:6px 14px" onclick="document.getElementById(\'create-agent-form\').style.display=\'none\'">Cancel</button>';
  html += '</div>';
  html += '<div id="create-agent-error" style="color:#ef4444;font-size:0.78rem;margin-top:6px"></div>';
  html += '</div>';

  // Editor Modal (hidden) — full-featured code editor
  html += '<div id="agent-editor-modal" style="display:none;position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,0.85);align-items:center;justify-content:center">';
  html += '<div style="background:#0d1117;border:1px solid rgba(139,92,246,0.25);border-radius:14px;width:780px;max-width:92vw;max-height:85vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,0.6)">';
  // Editor header
  html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid rgba(255,255,255,0.08);background:rgba(255,255,255,0.02);border-radius:14px 14px 0 0">';
  html += '<div style="display:flex;align-items:center;gap:10px">';
  html += '<div style="font-weight:600;color:var(--text-primary);font-size:0.95rem" id="editor-title">Edit Agent</div>';
  html += '<span id="editor-lang-badge" style="font-size:0.68rem;padding:2px 8px;border-radius:10px;background:rgba(16,185,129,0.15);color:#10b981">Python</span>';
  html += '</div>';
  html += '<div style="display:flex;gap:6px;align-items:center">';
  html += '<span id="editor-status" style="font-size:0.72rem;color:var(--text-muted)"></span>';
  html += '<button class="btn" style="font-size:0.78rem;padding:4px 12px" onclick="closeAgentEditor()">✕ Close</button>';
  html += '</div></div>';
  // Editor hint
  html += '<div id="editor-hint" style="font-size:0.76rem;color:var(--text-muted);padding:8px 18px;background:rgba(139,92,246,0.05);border-bottom:1px solid rgba(255,255,255,0.04)"></div>';
  // Editor body with line numbers
  html += '<div style="flex:1;display:flex;overflow:hidden;min-height:0">';
  html += '<div id="editor-line-numbers" style="width:48px;padding:12px 6px;text-align:right;font-family:Consolas,\'Courier New\',monospace;font-size:0.78rem;line-height:1.65;color:rgba(255,255,255,0.2);background:rgba(0,0,0,0.3);overflow:hidden;user-select:none;flex-shrink:0"></div>';
  html += '<textarea id="agent-editor-content" style="flex:1;border:none;outline:none;background:#0d1117;color:#e6edf3;font-family:Consolas,\'Courier New\',monospace;font-size:0.82rem;padding:12px 14px;resize:none;line-height:1.65;tab-size:4;white-space:pre;overflow-wrap:normal;overflow-x:auto" spellcheck="false" autocomplete="off" autocorrect="off" autocapitalize="off"></textarea>';
  html += '</div>';
  // Editor footer
  html += '<div style="display:flex;gap:8px;padding:10px 18px;justify-content:space-between;align-items:center;border-top:1px solid rgba(255,255,255,0.06);background:rgba(255,255,255,0.02);border-radius:0 0 14px 14px">';
  html += '<div style="font-size:0.72rem;color:var(--text-muted)" id="editor-cursor-pos">Ln 1, Col 1</div>';
  html += '<div style="display:flex;gap:6px">';
  html += '<span style="font-size:0.7rem;color:var(--text-muted);padding:4px 8px;background:rgba(255,255,255,0.04);border-radius:6px">Tab ↹ Indent</span>';
  html += '<span style="font-size:0.7rem;color:var(--text-muted);padding:4px 8px;background:rgba(255,255,255,0.04);border-radius:6px">Ctrl+S Save</span>';
  html += '</div>';
  html += '<div style="display:flex;gap:6px">';
  html += '<button class="btn" style="font-size:0.82rem;padding:6px 16px" onclick="closeAgentEditor()">Cancel</button>';
  html += '<button class="btn btn-primary" style="font-size:0.82rem;padding:6px 16px" onclick="saveAgentContent()">💾 Save</button>';
  html += '</div></div></div></div>';

  // Output Viewer Modal
  html += '<div id="agent-output-modal" style="display:none;position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,0.85);align-items:center;justify-content:center">';
  html += '<div style="background:#0d1117;border:1px solid rgba(139,92,246,0.2);border-radius:14px;width:700px;max-width:90vw;max-height:80vh;display:flex;flex-direction:column;padding:20px;box-shadow:0 20px 60px rgba(0,0,0,0.5)">';
  html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">';
  html += '<div style="font-weight:600;color:var(--text-primary);font-size:1rem" id="output-viewer-title">Agent Outputs</div>';
  html += '<button class="btn" style="font-size:0.8rem;padding:4px 12px" onclick="closeOutputViewer()">✕ Close</button>';
  html += '</div>';
  html += '<div id="output-viewer-content" style="flex:1;overflow-y:auto;padding:4px"></div>';
  html += '</div></div>';

  el.innerHTML = html;

  // Load log
  try {
    var logData = await api('/api/agents/log');
    var logEl = document.getElementById('agent-log');
    var entries = logData.log || [];
    if (entries.length === 0) {
      logEl.innerHTML = '<div style="color:var(--text-muted);font-size:0.82rem">No runs yet. Enable an agent or click "Run Now".</div>';
    } else {
      function _buildLogRow(e) {
        var icon = e.status === 'ok' ? '✅' : e.status === 'needs_approval' ? '🔒' : '❌';
        var typeBadge = e.type === 'python' ? '🐍' : '🤖';
        var t = (e.timestamp || '').replace('T',' ').substring(5,16);
        var output = e.output ? e.output.substring(0,80).replace(/</g,'&lt;') : '';
        var err = e.error ? '<span style="color:#ef4444"> ' + e.error.substring(0,60) + '</span>' : '';
        return '<tr style="border-bottom:1px solid rgba(255,255,255,0.04)">' +
          '<td style="padding:4px 8px">' + icon + '</td>' +
          '<td style="padding:4px 8px;color:var(--text-muted);font-size:0.78rem">' + t + '</td>' +
          '<td style="padding:4px 8px;font-size:0.78rem">' + typeBadge + ' ' + e.name + '</td>' +
          '<td style="padding:4px 8px;font-size:0.78rem;color:var(--text-muted)">' + e.duration + 's</td>' +
          '<td style="padding:4px 8px;font-size:0.75rem;color:var(--text-muted);max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + output + err + '</td></tr>';
      }
      var LOG_PREVIEW = 5;
      var previewRows = entries.slice(0, LOG_PREVIEW).map(_buildLogRow).join('');
      var allRows = entries.map(_buildLogRow).join('');
      var showMoreBtn = entries.length > LOG_PREVIEW
        ? '<div style="text-align:center;margin-top:10px" id="log-expand-wrap"><button class="btn btn-sm btn-ghost" id="expand-log-btn" style="font-size:0.78rem">Show All ' + entries.length + ' Entries ▼</button></div>'
        : '';
      var tableHeader = '<table style="width:100%;border-collapse:collapse"><thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1)"><th style="padding:4px 8px;text-align:left;font-size:0.72rem;color:var(--text-muted)"></th><th style="text-align:left;font-size:0.72rem;color:var(--text-muted);padding:4px 8px">Time</th><th style="text-align:left;font-size:0.72rem;color:var(--text-muted);padding:4px 8px">Agent</th><th style="text-align:left;font-size:0.72rem;color:var(--text-muted);padding:4px 8px">Dur</th><th style="text-align:left;font-size:0.72rem;color:var(--text-muted);padding:4px 8px">Output</th></tr></thead><tbody id="log-tbody">';
      logEl.innerHTML = tableHeader + previewRows + '</tbody></table>' + showMoreBtn;
      // Bind expand/collapse
      var expandBtn = document.getElementById('expand-log-btn');
      if (expandBtn) {
        expandBtn.addEventListener('click', function() {
          var tbody = document.getElementById('log-tbody');
          var wrap = document.getElementById('log-expand-wrap');
          if (this.dataset.expanded === '1') {
            tbody.innerHTML = previewRows;
            this.textContent = 'Show All ' + entries.length + ' Entries ▼';
            this.dataset.expanded = '0';
          } else {
            tbody.innerHTML = allRows;
            this.textContent = 'Show Less ▲';
            this.dataset.expanded = '1';
          }
        });
      }
    }
  } catch(e) {}
}

// Agent action functions
window.toggleAgent = async function(name, enabled) {
  try {
    var r = await fetch('/api/agents/' + name + '/toggle', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({enabled:enabled})
    });
    var data = await r.json();
    if (data.ok) {
      showToast(name + (enabled ? ' enabled' : ' disabled'), 'success');
    } else {
      showToast('Toggle failed: ' + (data.error || 'unknown'), 'warning');
      navigate('agents'); // refresh to show actual state
    }
  } catch(e) {
    showToast('Failed to toggle agent', 'warning');
    navigate('agents'); // refresh to show actual state
  }
};
window.runAgentNow = async function(name) {
  showToast('Running ' + name + '...', 'success');
  var result = await fetch('/api/agents/' + name + '/run', { method:'POST' }).then(r => r.json());
  if (result.status === 'ok') {
    showToast(name + ' completed (' + result.duration.toFixed(1) + 's)', 'success');
  } else if (result.status === 'needs_approval') {
    showToast(name + ' needs approval — click "Approve & Run"', 'warning');
  } else {
    showToast(name + ' failed: ' + (result.error || ''), 'warning');
  }
  navigate('agents');
};
window.approveAgent = async function(name) {
  await fetch('/api/agents/' + name + '/approve', { method:'POST' });
  showToast(name + ' approved! Running...', 'success');
  await window.runAgentNow(name);
};
window.confirmDeleteAgent = function(slug, displayName) {
  var overlay = document.createElement('div');
  overlay.id = 'delete-confirm-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;animation:fadeIn 0.15s ease';
  overlay.innerHTML = '<div style="background:#111827;border:1px solid rgba(239,68,68,0.3);border-radius:16px;padding:24px 28px;max-width:380px;width:90%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,0.5)">'
    + '<div style="font-size:2.2rem;margin-bottom:12px">🗑️</div>'
    + '<div style="font-size:1rem;font-weight:600;color:var(--text);margin-bottom:8px">Delete Agent</div>'
    + '<div style="color:var(--text-muted);font-size:0.85rem;margin-bottom:20px;line-height:1.5">Are you sure you want to delete <strong style="color:#ef4444">' + displayName + '</strong>?<br>This action cannot be undone.</div>'
    + '<div style="display:flex;gap:10px;justify-content:center">'
    + '<button class="btn" style="padding:8px 20px;font-size:0.85rem" onclick="document.getElementById(\'delete-confirm-overlay\').remove()">Cancel</button>'
    + '<button class="btn" style="padding:8px 20px;font-size:0.85rem;background:rgba(239,68,68,0.2);color:#ef4444;border-color:rgba(239,68,68,0.4)" onclick="deleteAgent(\'' + slug + '\')">Delete</button>'
    + '</div></div>';
  overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
};
window.deleteAgent = async function(slug) {
  var overlay = document.getElementById('delete-confirm-overlay');
  if (overlay) overlay.remove();
  try {
    var r = await fetch('/api/agents/' + slug, { method:'DELETE' });
    var data = await r.json();
    if (data.ok) {
      showToast(slug + ' deleted', 'success');
    } else {
      showToast('Delete failed: ' + (data.error || 'unknown'), 'warning');
    }
  } catch(e) {
    showToast('Failed to delete agent', 'warning');
  }
  navigate('agents');
};

// Editor functions
var _editingAgentName = '';
var _editingAgentType = '';

function _updateLineNumbers() {
  var ta = document.getElementById('agent-editor-content');
  var nums = document.getElementById('editor-line-numbers');
  if (!ta || !nums) return;
  var lines = ta.value.split('\n').length;
  var html = '';
  for (var i = 1; i <= lines; i++) html += i + '\n';
  nums.textContent = html;
  // Sync scroll
  nums.scrollTop = ta.scrollTop;
}

function _updateCursorPos() {
  var ta = document.getElementById('agent-editor-content');
  var pos = document.getElementById('editor-cursor-pos');
  if (!ta || !pos) return;
  var text = ta.value.substring(0, ta.selectionStart);
  var line = text.split('\n').length;
  var col = ta.selectionStart - text.lastIndexOf('\n');
  pos.textContent = 'Ln ' + line + ', Col ' + col;
}

window.editAgent = async function(name) {
  _editingAgentName = name;
  var data = await fetch('/api/agents/' + name + '/content').then(r => r.json());
  if (!data.ok) { showToast('Cannot load agent', 'warning'); return; }
  _editingAgentType = data.type;
  document.getElementById('editor-title').textContent = (data.type === 'python' ? '🐍 ' : '🤖 ') + 'Edit: ' + name;
  var badge = document.getElementById('editor-lang-badge');
  if (data.type === 'python') {
    badge.textContent = 'Python';
    badge.style.background = 'rgba(16,185,129,0.15)';
    badge.style.color = '#10b981';
  } else {
    badge.textContent = 'Markdown';
    badge.style.background = 'rgba(139,92,246,0.15)';
    badge.style.color = '#8b5cf6';
  }
  document.getElementById('editor-hint').innerHTML = data.type === 'python'
    ? 'Must have a <code>run(context)</code> function. <b>output:</b> local, obsidian, webhook (comma-separated).'
    : 'Frontmatter (---) controls metadata. <b>output:</b> local, obsidian, webhook. Example: <code>output: local,obsidian</code>';
  var ta = document.getElementById('agent-editor-content');
  ta.value = data.content;
  document.getElementById('agent-editor-modal').style.display = 'flex';
  document.getElementById('editor-status').textContent = '';
  _updateLineNumbers();
  _updateCursorPos();

  // Bind editor events
  ta.onscroll = function() {
    document.getElementById('editor-line-numbers').scrollTop = ta.scrollTop;
  };
  ta.oninput = function() { _updateLineNumbers(); _updateCursorPos(); };
  ta.onclick = _updateCursorPos;
  ta.onkeyup = _updateCursorPos;

  // Tab key, auto-indent, bracket completion
  ta.onkeydown = function(e) {
    // Ctrl+S to save
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      saveAgentContent();
      return;
    }
    // Tab key — insert 4 spaces
    if (e.key === 'Tab') {
      e.preventDefault();
      var start = ta.selectionStart;
      var end = ta.selectionEnd;
      if (e.shiftKey) {
        // Shift+Tab: outdent current line
        var lineStart = ta.value.lastIndexOf('\n', start - 1) + 1;
        var lineText = ta.value.substring(lineStart, end);
        if (lineText.startsWith('    ')) {
          ta.value = ta.value.substring(0, lineStart) + lineText.substring(4);
          ta.selectionStart = Math.max(lineStart, start - 4);
          ta.selectionEnd = Math.max(lineStart, end - 4);
        }
      } else {
        ta.value = ta.value.substring(0, start) + '    ' + ta.value.substring(end);
        ta.selectionStart = ta.selectionEnd = start + 4;
      }
      _updateLineNumbers();
      return;
    }
    // Enter — auto-indent
    if (e.key === 'Enter') {
      e.preventDefault();
      var start = ta.selectionStart;
      var lineStart = ta.value.lastIndexOf('\n', start - 1) + 1;
      var currentLine = ta.value.substring(lineStart, start);
      var indent = currentLine.match(/^(\s*)/)[1];
      // Add extra indent after : (def, if, for, class, etc.)
      if (currentLine.trimEnd().endsWith(':')) indent += '    ';
      ta.value = ta.value.substring(0, start) + '\n' + indent + ta.value.substring(ta.selectionEnd);
      ta.selectionStart = ta.selectionEnd = start + 1 + indent.length;
      _updateLineNumbers();
      return;
    }
    // Auto-close brackets
    var pairs = {'(': ')', '[': ']', '{': '}', '"': '"', "'": "'"};
    if (pairs[e.key] && ta.selectionStart === ta.selectionEnd) {
      e.preventDefault();
      var s = ta.selectionStart;
      ta.value = ta.value.substring(0, s) + e.key + pairs[e.key] + ta.value.substring(s);
      ta.selectionStart = ta.selectionEnd = s + 1;
      return;
    }
  };

  setTimeout(function() { ta.focus(); }, 100);
};
window.closeAgentEditor = function() {
  document.getElementById('agent-editor-modal').style.display = 'none';
  _editingAgentName = '';
};
window.saveAgentContent = async function() {
  var content = document.getElementById('agent-editor-content').value;
  var statusEl = document.getElementById('editor-status');
  statusEl.textContent = 'Saving...';
  statusEl.style.color = '#f59e0b';
  var saveHdrs = {'Content-Type': 'application/json'};
  if (_editingAgentType === 'python') saveHdrs['X-Confirm'] = 'true';
  var r = await fetch('/api/agents/' + _editingAgentName + '/content', {
    method: 'PUT', headers: saveHdrs,
    body: JSON.stringify({ content: content })
  }).then(r => r.json());
  if (r.ok) {
    statusEl.textContent = '✓ Saved';
    statusEl.style.color = '#10b981';
    showToast(_editingAgentName + ' saved!', 'success');
    setTimeout(function() { closeAgentEditor(); navigate('agents'); }, 600);
  } else {
    statusEl.textContent = '✕ Failed';
    statusEl.style.color = '#ef4444';
    showToast(r.error || 'Save failed', 'warning');
  }
};

window.viewAgentOutputs = async function(name) {
  document.getElementById('output-viewer-title').textContent = '📄 Outputs: ' + name;
  var el = document.getElementById('output-viewer-content');
  el.innerHTML = '<div class="spinner"></div>';
  document.getElementById('agent-output-modal').style.display = 'flex';

  var data = await fetch('/api/agents/' + name + '/outputs').then(function(r) { return r.json(); });
  var outputs = data.outputs || [];

  if (outputs.length === 0) {
    el.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:40px">No outputs yet. Run the agent to generate output.</div>';
    return;
  }

  function _renderOutput(o) {
    return '<div style="background:rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.06);border-radius:10px;padding:14px;margin-bottom:10px">'
      + '<div style="font-size:0.78rem;color:var(--accent);margin-bottom:8px;font-weight:600">' + o.date + '</div>'
      + '<div style="font-size:0.82rem;color:var(--text);white-space:pre-wrap;line-height:1.6;max-height:300px;overflow-y:auto">' + o.content.replace(/</g, '&lt;').replace(/\n/g, '<br>') + '</div>'
      + '</div>';
  }

  // Show latest output
  var html = '<div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:8px">Latest run</div>';
  html += _renderOutput(outputs[0]);

  // Show all runs button (if more than 1)
  if (outputs.length > 1) {
    html += '<div style="text-align:center;margin:12px 0">'
      + '<button class="btn btn-ghost btn-sm" id="show-all-outputs-btn" style="font-size:0.78rem" onclick="toggleAllOutputs()">📜 Show all ' + outputs.length + ' runs ▼</button>'
      + '</div>';
    html += '<div id="all-outputs-list" style="display:none">';
    html += '<div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:8px">Previous runs</div>';
    outputs.slice(1).forEach(function(o) { html += _renderOutput(o); });
    html += '</div>';
  } else {
    html += '<div style="font-size:0.78rem;color:var(--text-muted);margin-top:4px">1 total run</div>';
  }

  el.innerHTML = html;
};

window.toggleAllOutputs = function() {
  var list = document.getElementById('all-outputs-list');
  var btn = document.getElementById('show-all-outputs-btn');
  if (!list || !btn) return;
  if (list.style.display === 'none') {
    list.style.display = 'block';
    btn.textContent = '📜 Hide previous runs ▲';
  } else {
    list.style.display = 'none';
    btn.textContent = btn.textContent.replace('▲', '▼').replace('Hide previous runs', 'Show all runs');
  }
};

window.closeOutputViewer = function() {
  document.getElementById('agent-output-modal').style.display = 'none';
};

var _pendingAgentType = '';
window.createAgent = function(type) {
  _pendingAgentType = type;
  var form = document.getElementById('create-agent-form');
  var input = document.getElementById('new-agent-name');
  var errEl = document.getElementById('create-agent-error');
  errEl.textContent = '';
  input.value = '';
  form.style.display = 'block';
  input.focus();
  // Bind Enter key
  input.onkeydown = function(e) {
    if (e.key === 'Enter') { e.preventDefault(); _confirmCreateAgent(); }
    if (e.key === 'Escape') { form.style.display = 'none'; }
  };
  document.getElementById('confirm-create-agent').onclick = _confirmCreateAgent;
};

async function _confirmCreateAgent() {
  var input = document.getElementById('new-agent-name');
  var errEl = document.getElementById('create-agent-error');
  var name = input.value.trim().toLowerCase().replace(/\s+/g, '-');
  if (!name) { errEl.textContent = 'Name is required'; return; }
  if (!/^[a-z0-9\-]+$/.test(name)) { errEl.textContent = 'Only lowercase letters, numbers, and hyphens allowed'; return; }
  errEl.textContent = '';
  var hdrs = {'Content-Type':'application/json'};
  if (_pendingAgentType === 'python') hdrs['X-Confirm'] = 'true';
  var result = await fetch('/api/agents/create', {
    method:'POST', headers:hdrs,
    body:JSON.stringify({name:name, type:_pendingAgentType})
  }).then(r => r.json());
  if (result.ok) {
    document.getElementById('create-agent-form').style.display = 'none';
    showToast('Created ' + name + ' — opening editor', 'success');
    setTimeout(function() { navigate('agents'); setTimeout(function() { editAgent(name); }, 300); }, 200);
  } else {
    errEl.textContent = result.error || 'Failed to create agent';
  }
}

window.importAgentFile = async function(input) {
  if (!input.files || !input.files[0]) return;
  var file = input.files[0];
  var reader = new FileReader();
  reader.onload = async function(e) {
    var content = e.target.result;
    var name = file.name.replace(/\.(py|md)$/, '').toLowerCase().replace(/\s+/g, '-');
    var type = file.name.endsWith('.py') ? 'python' : 'markdown';
    // Create agent first
    var createHdrs = {'Content-Type':'application/json'};
    if (type === 'python') createHdrs['X-Confirm'] = 'true';
    var r = await fetch('/api/agents/create', { method:'POST', headers:createHdrs, body:JSON.stringify({name:name, type:type}) }).then(r => r.json());
    if (r.ok) {
      // Write imported content
      var importHdrs = {'Content-Type':'application/json'};
      if (type === 'python') importHdrs['X-Confirm'] = 'true';
      await fetch('/api/agents/' + name + '/content', { method:'PUT', headers:importHdrs, body:JSON.stringify({content:content}) });
      showToast('Imported ' + file.name, 'success');
      navigate('agents');
    } else if (r.error && r.error.includes('exists')) {
      if (confirm('Agent "' + name + '" already exists. Overwrite?')) {
        var overwriteHdrs = {'Content-Type':'application/json'};
        if (type === 'python') overwriteHdrs['X-Confirm'] = 'true';
        await fetch('/api/agents/' + name + '/content', { method:'PUT', headers:overwriteHdrs, body:JSON.stringify({content:content}) });
        showToast('Updated ' + name, 'success');
        navigate('agents');
      }
    } else {
      showToast(r.error || 'Import failed', 'warning');
    }
  };
  reader.readAsText(file);
  input.value = '';  // Reset so same file can be re-imported
};

window.openAgentInEditor = async function(name) {
  var r = await fetch('/api/agents/' + name + '/open', { method:'POST' }).then(r => r.json());
  if (r.ok) {
    showToast('Opened in system editor', 'success');
  } else {
    showToast(r.error || 'Could not open file', 'warning');
  }
};

// ── Settings Tab ───────────────────────────────────────────────────
