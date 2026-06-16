const socket = new WebSocket('ws://localhost:8765');

const logsDiv      = document.getElementById('logs');
const statusBar    = document.getElementById('agent-status-bar');
const userInput    = document.getElementById('user-input');
const sendBtn      = document.getElementById('send-btn');
const settingsPanel = document.getElementById('settings-panel');
const toggleSettings = document.getElementById('toggle-settings');
const btnClear     = document.getElementById('btn-clear');
const btnUndo      = document.getElementById('btn-undo');
const btnSummarise = document.getElementById('btn-summarise');

// ── Streaming state ────────────────────────────────────────────────────────────
let currentAgentBubble = null;
let currentAgentText   = "";
let sessionTotalTokens = 0;
const SESSION_START    = new Date();

function startAgentBubble() {
  currentAgentText   = "";
  currentAgentBubble = document.createElement('div');
  currentAgentBubble.className = 'msg-bubble agent-response';
  const label = document.createElement('span');
  label.className   = 'bubble-label';
  label.textContent = 'Agent: ';
  const body = document.createElement('span');
  body.className = 'bubble-body';
  currentAgentBubble.appendChild(label);
  currentAgentBubble.appendChild(body);
  logsDiv.appendChild(currentAgentBubble);
  logsDiv.scrollTop = logsDiv.scrollHeight;
}

function appendToken(token) {
  if (!currentAgentBubble) startAgentBubble();
  currentAgentText += token;
  currentAgentBubble.querySelector('.bubble-body').textContent = currentAgentText;
  logsDiv.scrollTop = logsDiv.scrollHeight;
}

function finaliseAgentBubble() {
  currentAgentBubble = null;
  currentAgentText   = "";
}

// ── Tool rows ──────────────────────────────────────────────────────────────────
function addToolRow(icon, text, className) {
  const row = document.createElement('div');
  row.className = `tool-row ${className}`;
  row.innerHTML = `<span class="tool-icon">${icon}</span><span class="tool-text">${escHtml(text)}</span>`;
  logsDiv.appendChild(row);
  logsDiv.scrollTop = logsDiv.scrollHeight;
}

// ── Session save ───────────────────────────────────────────────────────────────
function saveSessionToServer() {
  const sessionEnd = new Date();
  const header = [
    `Session Start : ${SESSION_START.toLocaleString()}`,
    `Session End   : ${sessionEnd.toLocaleString()}`,
    `Duration      : ${Math.round((sessionEnd - SESSION_START) / 1000)}s`,
    `Total Tokens  : ~${Number(sessionTotalTokens).toLocaleString()}`,
    '─'.repeat(60),
    ''
  ].join('\n');

  const lines = [];
  logsDiv.querySelectorAll('.msg-bubble, .tool-row').forEach(el => {
    const label = el.querySelector('.bubble-label');
    const body  = el.querySelector('.bubble-body');
    if (label && body) {
      lines.push(`[${label.textContent}] ${body.textContent}`);
    } else {
      lines.push(el.innerText);
    }
  });

  const timestamp = SESSION_START.toISOString().replace(/[:.]/g, '-');
  socket.send(JSON.stringify({
    type:     'save_session',
    filename: `session_${timestamp}.txt`,
    content:  header + lines.join('\n'),
  }));
}

// ── WebSocket ──────────────────────────────────────────────────────────────────
toggleSettings.addEventListener('click', () => settingsPanel.classList.toggle('hidden'));

socket.onopen = () => socket.send(jsonStringifyEvent("get_config"));

socket.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  if (msg.type === "config") {
    document.getElementById('cfg-key').value   = msg.data.GEMINI_API_KEY || '';
    document.getElementById('cfg-model').value = msg.data.GEMINI_MODEL   || '';
    document.getElementById('cfg-dir').value   = msg.data.AGENT_WORK_DIR || '';
    document.getElementById('cfg-theme').value = msg.data.THEME          || 'dark';
    applyTheme(msg.data.THEME);
  }
  else if (msg.type === "status") {
    const clean = msg.content.replace(/[\r\n]/g, '').trim();
    if (clean) {
      statusBar.textContent = clean;
      // Also show persistent upload confirmations in chat log
      if (clean.startsWith("File uploaded") || clean.startsWith("File attached") || clean.startsWith("Session saved")) {
        appendOutputMessage('✔ ' + clean, 'status-msg');
      }
    }
  }
  else if (msg.type === "summarised") {
    appendOutputMessage(`📋 Summary: ${msg.content}`, 'status-msg');
    statusBar.textContent = '';
  }
  else if (msg.type === "tool_start") {
    statusBar.textContent = `⚙  ${msg.content}`;
    addToolRow('⚙', msg.content, 'tool-start');
  }
  else if (msg.type === "tool_done") {
    statusBar.textContent = '';
    addToolRow('✓', msg.content, 'tool-done');
  }
  else if (msg.type === "token") {
    statusBar.textContent = '';
    appendToken(msg.content);
  }
  else if (msg.type === "done") {
    finaliseAgentBubble();
    statusBar.textContent = '';
  }
  else if (msg.type === "token_count") {
    sessionTotalTokens    = msg.content;   // single assignment
    statusBar.textContent = `Context: ~${Number(msg.content).toLocaleString()} tokens`;
  }
  else if (msg.type === "error") {
    finaliseAgentBubble();
    appendOutputMessage('⚠ ' + msg.content, 'error-response');
    statusBar.textContent = '';
  }
};

// ── Settings ───────────────────────────────────────────────────────────────────
document.getElementById('save-settings').addEventListener('click', () => {
  const payload = {
    GEMINI_API_KEY: document.getElementById('cfg-key').value,
    GEMINI_MODEL:   document.getElementById('cfg-model').value,
    AGENT_WORK_DIR: document.getElementById('cfg-dir').value,
    THEME:          document.getElementById('cfg-theme').value,
  };
  socket.send(jsonStringifyEvent("save_config", payload));
  applyTheme(payload.THEME);
  settingsPanel.classList.add('hidden');
});

// ── Send message ───────────────────────────────────────────────────────────────
sendBtn.addEventListener('click', dispatchMessage);
userInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') dispatchMessage(); });

function dispatchMessage() {
  const txt = userInput.value.trim();
  if (!txt) return;
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble user-query';
  const label = document.createElement('span');
  label.className   = 'bubble-label';
  label.textContent = 'You: ';
  const body = document.createElement('span');
  body.className    = 'bubble-body';
  body.textContent  = txt;
  bubble.appendChild(label);
  bubble.appendChild(body);
  logsDiv.appendChild(bubble);
  logsDiv.scrollTop = logsDiv.scrollHeight;
  socket.send(jsonStringifyEvent("user_message", txt));
  userInput.value = "";
}

// ── Tauri file drop ────────────────────────────────────────────────────────
if (window.__TAURI__) {
  const { getCurrentWebviewWindow } = window.__TAURI__.webviewWindow;
  getCurrentWebviewWindow().onDragDropEvent((event) => {
    if (event.payload.type === 'drop') {
      event.payload.paths.forEach(path => {
        const name = path.split(/[\\/]/).pop();
        if (socket.readyState !== WebSocket.OPEN) {
          appendOutputMessage('⚠ WebSocket not connected.', 'error-response');
          return;
        }
        socket.send(JSON.stringify({ type: 'attach_file', name, path }));
        appendOutputMessage(`📎 Attaching: ${name}`, 'status-msg');
      });
      dropZone.classList.remove('drag-over');
    } else if (event.payload.type === 'enter' || event.payload.type === 'over') {
      dropZone.classList.add('drag-over');
    } else if (event.payload.type === 'leave' || event.payload.type === 'cancel') {
      dropZone.classList.remove('drag-over');
    }
  });
} else {
  console.warn('Not running in Tauri — file drop unavailable.');
}

// ── Absolute path attach ───────────────────────────────────────────────────────
document.getElementById('attach-path-btn').addEventListener('click', attachPath);
document.getElementById('path-input').addEventListener('keypress', (e) => {
  if (e.key === 'Enter') attachPath();
});

function attachPath() {
  const path = document.getElementById('path-input').value.trim();
  if (!path) return;
  const name = path.split(/[\\/]/).pop();
  if (socket.readyState !== WebSocket.OPEN) {
    appendOutputMessage('⚠ WebSocket not connected.', 'error-response');
    return;
  }
  socket.send(JSON.stringify({ type: 'attach_file', name, path }));
  document.getElementById('path-input').value = '';
  // Confirmation shown when server sends back status message
}

// ── History controls ───────────────────────────────────────────────────────
btnClear.addEventListener('click', () => {
  if (!confirm('Clear chat history? (UI log kept, files kept)')) return;
  socket.send(JSON.stringify({ type: 'clear' }));
  // Add marker to session log only
  appendOutputMessage('**cleared chat history**', 'status-msg');
});

btnUndo.addEventListener('click', () => {
  if (!confirm('Remove last user+agent turn from history?')) return;
  socket.send(JSON.stringify({ type: 'undo' }));
  appendOutputMessage('**undo chat history (1 user assistant turn)**', 'status-msg');
});

btnSummarise.addEventListener('click', () => {
  if (!confirm('Summarise history to save tokens? This sends history to the LLM once.')) return;
  socket.send(JSON.stringify({ type: 'summarise' }));
  appendOutputMessage('**history summarised by user**', 'status-msg');
  statusBar.textContent = 'Summarising history…';
});

// ── Helpers ────────────────────────────────────────────────────────────────────
function appendOutputMessage(text, className) {
  const el = document.createElement('div');
  el.className  = `msg-bubble ${className}`;
  el.textContent = text;
  logsDiv.appendChild(el);
  logsDiv.scrollTop = logsDiv.scrollHeight;
}

function applyTheme(theme) {
  document.body.classList.toggle('light-theme', theme === 'light');
  document.body.classList.toggle('dark-theme',  theme !== 'light');
}

function escHtml(str) {
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

window.addEventListener('beforeunload', () => {
  if (socket.readyState === WebSocket.OPEN) {
    saveSessionToServer();
    socket.send(JSON.stringify({ type: 'shutdown' }));
  }
});

function jsonStringifyEvent(type, content = {}) {
  return JSON.stringify({
    type,
    [typeof content === 'string' ? 'content' : 'data']: content,
  });
}