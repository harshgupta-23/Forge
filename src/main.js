const socket = new WebSocket('ws://localhost:8765');

const logsDiv      = document.getElementById('logs');
const statusBar    = document.getElementById('agent-status-bar');
const userInput    = document.getElementById('user-input');
const sendBtn      = document.getElementById('send-btn');
const settingsPanel = document.getElementById('settings-panel');
const toggleSettings = document.getElementById('toggle-settings');
const closeSettings = document.getElementById('close-settings');
const btnNewSession = document.getElementById('btn-new-session');
const btnUndo      = document.getElementById('btn-undo');
const btnSummarise = document.getElementById('btn-summarise');
const btnTreeView  = document.getElementById('btn-tree-view');
const treeViewPanel = document.getElementById('tree-view-panel');
const closeTreeView = document.getElementById('close-tree-view');
const treeContainer = document.getElementById('tree-container');
const btnFetchSession      = document.getElementById('btn-fetch-session');
const sessionPickerPanel   = document.getElementById('session-picker-panel');
const closeSessionPicker   = document.getElementById('close-session-picker');
const sessionListContainer = document.getElementById('session-list-container');
const btnStop = document.getElementById('btn-stop');
const tokens5hEl  = document.getElementById('tokens-5h');
const tokens24hEl = document.getElementById('tokens-24h');

// ── Reusable SVG Icons (cross-platform, Linux-safe) ───────────────────────────
const ICONS = {
  CHECK: `<svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  GEAR: `<svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
  EDIT: `<svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`,
  TRASH: `<svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`,
  PLAY: `<svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>`,
  ZAP: `<svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
  CLIP: `<svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>`,
  ALERT: `<svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`
};

// ── Global Pan and Zoom state (n8n-style) ──────────────────────────────────────
let panX = 40;
let panY = 40;
let zoomScale = 1.0;
let isDragging = false;
let startX = 0;
let startY = 0;
let currentResizeListener = null;

function updateTreeTransform() {
  const layout = document.getElementById('tree-layout');
  if (layout) {
    layout.style.transform = `translate(${panX}px, ${panY}px) scale(${zoomScale})`;
  }
}

function setupPanZoom() {
  treeContainer.style.overflow = 'hidden';
  treeContainer.style.cursor = 'grab';
  treeContainer.style.position = 'relative';
  
  treeContainer.addEventListener('wheel', (e) => {
    const layout = document.getElementById('tree-layout');
    if (!layout) return;
    e.preventDefault();
    
    const rect = treeContainer.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    
    // Zoom relative to the mouse cursor position
    const layoutX = (mouseX - panX) / zoomScale;
    const layoutY = (mouseY - panY) / zoomScale;
    
    zoomScale += e.deltaY * -0.001;
    zoomScale = Math.min(Math.max(0.3, zoomScale), 3.0);
    
    panX = mouseX - layoutX * zoomScale;
    panY = mouseY - layoutY * zoomScale;
    
    updateTreeTransform();
  }, { passive: false });
  
  treeContainer.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    if (e.target.closest('.node-btn') || e.target.closest('input') || e.target.closest('.tree-node-card')) {
      return;
    }
    isDragging = true;
    treeContainer.style.cursor = 'grabbing';
    startX = e.clientX - panX;
    startY = e.clientY - panY;
    e.preventDefault();
  });
  
  window.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    panX = e.clientX - startX;
    panY = e.clientY - startY;
    updateTreeTransform();
  });
  
  window.addEventListener('mouseup', () => {
    if (isDragging) {
      isDragging = false;
      treeContainer.style.cursor = 'grab';
    }
  });
}

// Initialize on page load
setupPanZoom();

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
  if (currentAgentBubble) {
    const body = currentAgentBubble.querySelector('.bubble-body');
    body.innerHTML = renderMarkdown(currentAgentText);  // swap textContent → rendered HTML
  }
  currentAgentBubble = null;
  currentAgentText   = "";
}

// ── Connection Indicator ───────────────────────────────────────────────────────
const connectionBanner = document.getElementById('connection-banner');
document.getElementById('btn-reconnect').addEventListener('click', () => location.reload());

socket.addEventListener('close', () => {
  connectionBanner.classList.remove('hidden');
  sendBtn.disabled = true;
  userInput.disabled = true;
});
socket.addEventListener('error', () => {
  connectionBanner.classList.remove('hidden');
});

// ── Tool rows ──────────────────────────────────────────────────────────────────
function addToolRow(icon, text, className) {
  const row = document.createElement('div');
  row.className = `tool-row ${className}`;
  row.innerHTML = `<span class="tool-icon">${icon}</span><span class="tool-text">${escHtml(text)}</span>`;
  logsDiv.appendChild(row);
  logsDiv.scrollTop = logsDiv.scrollHeight;
}

// ── Tree View Drawing ──────────────────────────────────────────────────────────
function renderChatHistory(pathMessages) {
  logsDiv.innerHTML = "";
  
  pathMessages.forEach(msg => {
    if (msg.type === "human") {
      appendOutputMessage(msg.content, 'user-query', 'You: ');
    } else if (msg.type === "ai") {
      if (msg.content && typeof msg.content === 'string' && !msg.content.includes('<tool_call>')) {
        appendOutputMessage(msg.content, 'agent-response', 'Agent: ');
      }
    } else if (msg.type === "tool") {
      const firstLine = msg.content ? msg.content.split('\n')[0].trim() : "";
      const summary = firstLine.substring(0, 80) + (firstLine.length > 80 ? '…' : '');
      addToolRow(ICONS.CHECK, `${msg.name} → ${summary}`, 'tool-done');
    }
  });
  
  logsDiv.scrollTop = logsDiv.scrollHeight;
}

function renderTreeView(nodes, rootId, activeNodeId) {
  treeContainer.innerHTML = "";
  
  const layout = document.createElement('div');
  layout.id = 'tree-layout';
  layout.style.position = 'absolute';
  layout.style.transformOrigin = '0 0';
  layout.style.transform = `translate(${panX}px, ${panY}px) scale(${zoomScale})`;
  layout.style.display = 'inline-block';
  layout.style.minWidth = '100%';
  layout.style.minHeight = '100%';
  
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.id = 'tree-svg';
  svg.style.position = 'absolute';
  svg.style.top = '0';
  svg.style.left = '0';
  svg.style.width = '100%';
  svg.style.height = '100%';
  svg.style.pointerEvents = 'none';
  svg.style.zIndex = '1';
  layout.appendChild(svg);
  
  const nodesRoot = document.createElement('div');
  nodesRoot.id = 'tree-nodes-root';
  nodesRoot.style.display = 'flex';
  nodesRoot.style.padding = '40px';
  nodesRoot.style.position = 'relative';
  nodesRoot.style.zIndex = '2';
  layout.appendChild(nodesRoot);
  
  treeContainer.appendChild(layout);
  
  const activePath = new Set();
  let curr = activeNodeId;
  while (curr) {
    activePath.add(curr);
    const node = nodes[curr];
    curr = node ? node.parent_id : null;
  }
  
  function buildBranchHTML(nodeId) {
    const node = nodes[nodeId];
    if (!node) return null;
    
    const branch = document.createElement('div');
    branch.className = 'tree-branch';
    
    const card = document.createElement('div');
    card.className = 'tree-node-card';
    card.id = `card-${nodeId}`;
    
    if (nodeId === activeNodeId) {
      card.classList.add('active-tip');
    } else if (activePath.has(nodeId)) {
      card.classList.add('active-path');
    } else {
      card.classList.add('inactive-branch');
    }
    
    const meta = document.createElement('div');
    meta.className = 'node-meta';
    
    const typeBadge = document.createElement('span');
    typeBadge.className = `node-type-badge ${node.type}`;
    typeBadge.textContent = node.type;
    meta.appendChild(typeBadge);
    
    if (node.label) {
      const labelBadge = document.createElement('span');
      labelBadge.className = 'node-label-badge';
      labelBadge.textContent = node.label;
      labelBadge.title = node.label;
      meta.appendChild(labelBadge);
    }
    
    card.appendChild(meta);
    
    const excerpt = document.createElement('div');
    excerpt.className = 'node-content-excerpt';
    
    if (node.type === "root") {
      excerpt.innerHTML = `${ICONS.PLAY} Start of Session`;
    } else if (node.type === "summary") {
      const summaryText = node.agent_message ? escHtml(node.agent_message.content.substring(0, 30)) : "Summary";
      excerpt.innerHTML = `${ICONS.ZAP} ${summaryText}`;
    } else {
      const query = node.user_message ? node.user_message.content : "";
      excerpt.textContent = query.substring(0, 30) + (query.length > 30 ? "…" : "");
    }
    card.appendChild(excerpt);
    
    const actions = document.createElement('div');
    actions.className = 'node-actions';
    
    const renameBtn = document.createElement('button');
    renameBtn.className = 'node-btn';
    renameBtn.innerHTML = `${ICONS.EDIT} Label`;
    renameBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const newLabel = prompt("Enter label for this branch/node:", node.label || "");
      if (newLabel !== null) {
        socket.send(JSON.stringify({
          type: "set_label",
          data: {
            node_id: nodeId,
            label: newLabel.trim()
          }
        }));
      }
    });
    actions.appendChild(renameBtn);
    card.appendChild(actions);
    
    card.addEventListener('click', () => {
      if (nodeId !== activeNodeId) {
        socket.send(JSON.stringify({
          type: "set_active",
          content: nodeId
        }));
      }
    });
    
    branch.appendChild(card);
    
    if (node.children_ids && node.children_ids.length > 0) {
      const childrenColumn = document.createElement('div');
      childrenColumn.className = 'tree-children-column';
      
      node.children_ids.forEach(childId => {
        const childBranch = buildBranchHTML(childId);
        if (childBranch) {
          childrenColumn.appendChild(childBranch);
        }
      });
      branch.appendChild(childrenColumn);
    }
    
    return branch;
  }
  
  const rootBranch = buildBranchHTML(rootId);
  if (rootBranch) {
    nodesRoot.appendChild(rootBranch);
  }
  
  // Untransformed coordinate calculation relative to scaled layout container
  function drawConnections() {
    svg.innerHTML = "";
    
    svg.setAttribute('width', layout.scrollWidth);
    svg.setAttribute('height', layout.scrollHeight);
    
    const lRect = layout.getBoundingClientRect();
    
    Object.keys(nodes).forEach(nodeId => {
      const node = nodes[nodeId];
      if (node.children_ids && node.children_ids.length > 0) {
        const parentCard = document.getElementById(`card-${nodeId}`);
        if (!parentCard) return;
        
        const pRect = parentCard.getBoundingClientRect();
        const x1 = (pRect.right - lRect.left) / zoomScale;
        const y1 = (pRect.top - lRect.top + pRect.height / 2) / zoomScale;
        
        node.children_ids.forEach(childId => {
          const childCard = document.getElementById(`card-${childId}`);
          if (!childCard) return;
          
          const cRect = childCard.getBoundingClientRect();
          const x2 = (cRect.left - lRect.left) / zoomScale;
          const y2 = (cRect.top - lRect.top + cRect.height / 2) / zoomScale;
          
          const offset = Math.abs(x2 - x1) / 2;
          const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
          path.setAttribute('d', `M ${x1} ${y1} C ${x1 + offset} ${y1}, ${x2 - offset} ${y2}, ${x2} ${y2}`);
          
          const isActiveSegment = activePath.has(nodeId) && activePath.has(childId);
          if (isActiveSegment) {
            path.setAttribute('stroke', 'var(--accent)');
            path.setAttribute('stroke-width', '3');
            path.setAttribute('style', 'filter: drop-shadow(0 0 3px var(--accent)); opacity: 0.95;');
          } else {
            path.setAttribute('stroke', 'var(--border-color)');
            path.setAttribute('stroke-width', '1.5');
            path.setAttribute('style', 'opacity: 0.6;');
          }
          path.setAttribute('fill', 'none');
          svg.appendChild(path);
        });
      }
    });
  }
  
  setTimeout(drawConnections, 50);
  
  if (currentResizeListener) {
    window.removeEventListener('resize', currentResizeListener);
  }
  currentResizeListener = drawConnections;
  window.addEventListener('resize', currentResizeListener);
}

function renderSessionList(sessions) {
  sessionListContainer.innerHTML = "";
  if (!sessions || sessions.length === 0) {
    sessionListContainer.innerHTML = '<p style="opacity:0.7;">No previous sessions found.</p>';
    return;
  }
  
  sessions.forEach(s => {
    const item = document.createElement('div');
    item.className = 'tree-node-card';
    item.style.cursor = 'pointer';
    item.style.marginBottom = '8px';
    
    const when = s.created_at ? new Date(s.created_at).toLocaleString() : 'Unknown date';
    const displayText = s.label || s.preview || '(empty)';

    // Updated HTML structure containing Rename and Delete buttons
    item.innerHTML = `
      <div class="node-meta"><span class="node-type-badge">${s.node_count} nodes</span></div>
      <div class="node-content-excerpt">${escHtml(displayText)}</div>
      <div style="font-size:11px; opacity:0.6; margin-top:4px;">${escHtml(when)}</div>
      <div class="node-actions">
        <button class="node-btn rename-session-btn">${ICONS.EDIT} Rename</button>
        <button class="node-btn delete-session-btn">${ICONS.TRASH} Delete</button>
      </div>
    `;

    // Click handler for the card itself (loads the session)
    item.addEventListener('click', () => {
      socket.send(JSON.stringify({ type: 'load_session', data: { session_id: s.session_id } }));
      sessionPickerPanel.classList.add('hidden');
    });

    // Event listener for Rename button (stops propagation so it doesn't trigger card click)
    item.querySelector('.rename-session-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      const newLabel = prompt("Label for this session:", s.label || "");
      if (newLabel !== null) {
        socket.send(JSON.stringify({ type: 'rename_session', data: { session_id: s.session_id, label: newLabel.trim() } }));
      }
    });

    // Event listener for Delete button (stops propagation so it doesn't trigger card click)
    item.querySelector('.delete-session-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      if (confirm('Delete this saved session permanently? This cannot be undone.')) {
        socket.send(JSON.stringify({ type: 'delete_session', data: { session_id: s.session_id } }));
      }
    });

    sessionListContainer.appendChild(item);
  });
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
toggleSettings.addEventListener('click', () => {
  settingsPanel.classList.toggle('hidden');
  treeViewPanel.classList.add('hidden');
});

btnTreeView.addEventListener('click', () => {
  treeViewPanel.classList.toggle('hidden');
  settingsPanel.classList.add('hidden');
  if (!treeViewPanel.classList.contains('hidden')) {
    // Reset zoom and center view slightly on open
    panX = 40;
    panY = 40;
    zoomScale = 1.0;
    updateTreeTransform();
    window.dispatchEvent(new Event('resize'));
  }
});

closeTreeView.addEventListener('click', () => {
  treeViewPanel.classList.add('hidden');
});

closeSettings.addEventListener('click', () => {
  settingsPanel.classList.add('hidden');
});

btnFetchSession.addEventListener('click', () => {
  sessionPickerPanel.classList.toggle('hidden');
  settingsPanel.classList.add('hidden');
  treeViewPanel.classList.add('hidden');
  if (!sessionPickerPanel.classList.contains('hidden')) {
    socket.send(JSON.stringify({ type: 'list_sessions' }));
  }
});

closeSessionPicker.addEventListener('click', () => {
  sessionPickerPanel.classList.add('hidden');
});

socket.onopen = () => {
  socket.send(jsonStringifyEvent("get_config"));
  socket.send(JSON.stringify({ type: 'get_token_usage' }));
};

socket.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  if (msg.type === "config") {
    document.getElementById('cfg-key').value   = msg.data.API_KEY  || '';
    document.getElementById('cfg-base').value  = msg.data.API_BASE || '';
    document.getElementById('cfg-model').value = msg.data.MODEL    || '';
    document.getElementById('cfg-dir').value   = msg.data.AGENT_WORK_DIR  || '';
    document.getElementById('cfg-theme').value = msg.data.THEME           || 'dark';
    applyTheme(msg.data.THEME);
  }
  else if (msg.type === "token_usage_windows") {
    tokens5hEl.textContent  = `5h: ~${Number(msg.last_5h).toLocaleString()}`;
    tokens24hEl.textContent = `24h: ~${Number(msg.last_24h).toLocaleString()}`;
  }
  else if (msg.type === "chat_history") {
    renderChatHistory(msg.messages);
  }
  else if (msg.type === "tree_data") {
    renderTreeView(msg.nodes, msg.root_id, msg.active_node_id);
  }
  else if (msg.type === "session_list") {
    renderSessionList(msg.sessions);
  }
  else if (msg.type === "status") {
    const clean = msg.content.replace(/[\r\n]/g, '').trim();
    if (clean) {
      statusBar.textContent = clean;
      // Also show persistent upload confirmations in chat log
      if (clean.startsWith("File uploaded") || clean.startsWith("File attached") || clean.startsWith("Session saved")) {
        appendOutputMessage(`${ICONS.CHECK} ${clean}`, 'status-msg');
      }
    }
  }
  else if (msg.type === "summarised") {
    appendOutputMessage(`${ICONS.ZAP} Summary: ${msg.content}`, 'status-msg');
    statusBar.textContent = '';
  }
  else if (msg.type === "tool_start") {
    statusBar.textContent = msg.content;
    addToolRow(ICONS.GEAR, msg.content, 'tool-start');
  }
  else if (msg.type === "tool_done") {
    statusBar.textContent = '';
    addToolRow(ICONS.CHECK, msg.content, 'tool-done');
  }
  else if (msg.type === "token") {
    statusBar.textContent = '';
    appendToken(msg.content);
  }
  else if (msg.type === "done") {
    finaliseAgentBubble();
    btnStop.classList.add('hidden');
    statusBar.textContent = '';
  }
  else if (msg.type === "token_count") {
    sessionTotalTokens    = msg.content;   // single assignment
    statusBar.textContent = `Context: ~${Number(msg.content).toLocaleString()} tokens`;
  }
  else if (msg.type === "error") {
    finaliseAgentBubble();
    appendOutputMessage(`${ICONS.ALERT} ${msg.content}`, 'error-response');
    btnStop.classList.add('hidden');
    statusBar.textContent = '';
  }
};

// ── Settings ───────────────────────────────────────────────────────────────────
document.getElementById('save-settings').addEventListener('click', () => {
  const payload = {
    API_KEY:  document.getElementById('cfg-key').value.trim(),
    API_BASE: document.getElementById('cfg-base').value.trim(),
    MODEL:    document.getElementById('cfg-model').value.trim(),
    AGENT_WORK_DIR:  document.getElementById('cfg-dir').value.trim(),
    THEME:           document.getElementById('cfg-theme').value,
  };
  socket.send(jsonStringifyEvent("save_config", payload));
  applyTheme(payload.THEME);
  settingsPanel.classList.add('hidden');
  // Request fresh config echo so UI fields stay in sync with what was persisted
  setTimeout(() => socket.send(jsonStringifyEvent("get_config")), 300);
});

// ── Send message ───────────────────────────────────────────────────────────────
sendBtn.addEventListener('click', dispatchMessage);
userInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') dispatchMessage(); });
btnStop.addEventListener('click', () => {
  socket.send(JSON.stringify({ type: 'stop_generation' }));
});

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
  btnStop.classList.remove('hidden');
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
          appendOutputMessage(`${ICONS.ALERT} WebSocket not connected.`, 'error-response');
          return;
        }
        socket.send(JSON.stringify({ type: 'attach_file', name, path }));
        appendOutputMessage(`${ICONS.CLIP} Attaching: ${name}`, 'status-msg');
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
    appendOutputMessage(`${ICONS.ALERT} WebSocket not connected.`, 'error-response');
    return;
  }
  socket.send(JSON.stringify({ type: 'attach_file', name, path }));
  document.getElementById('path-input').value = '';
  // Confirmation shown when server sends back status message
}

// ── History controls ───────────────────────────────────────────────────────
btnNewSession.addEventListener('click', () => {
  socket.send(JSON.stringify({ type: 'clear' }));
});

btnUndo.addEventListener('click', () => {
  if (!confirm('Remove last user+agent turn from history?')) return;
  socket.send(JSON.stringify({ type: 'undo' }));
});

btnSummarise.addEventListener('click', () => {
  if (!confirm('Summarise history to save tokens? This sends history to the LLM once.')) return;
  socket.send(JSON.stringify({ type: 'summarise' }));
  statusBar.textContent = 'Summarising history…';
});

// ── Helpers ────────────────────────────────────────────────────────────────────
function appendOutputMessage(text, className, labelText = "") {
  const el = document.createElement('div');
  el.className  = `msg-bubble ${className}`;
  if (labelText) {
    const label = document.createElement('span');
    label.className   = 'bubble-label';
    label.textContent = labelText;
    const body = document.createElement('span');
    body.className    = 'bubble-body';
    // Agent responses get markdown rendering; user input stays as plain text (XSS safety)
    if (className === 'agent-response') {
      body.innerHTML = renderMarkdown(text);
    } else {
      body.textContent = text;
    }
    el.appendChild(label);
    el.appendChild(body);
  } else {
    if (className === 'status-msg' || className === 'error-response') {
      el.innerHTML = text;
    } else {
      el.textContent = text;
    }
  }
  logsDiv.appendChild(el);
  logsDiv.scrollTop = logsDiv.scrollHeight;
}

function applyTheme(theme) {
  document.body.classList.toggle('light-theme', theme === 'light');
  document.body.classList.toggle('dark-theme',  theme !== 'light');
  // Swap highlight.js theme to match
  const hljsTheme = document.getElementById('hljs-theme');
  if (hljsTheme) {
    hljsTheme.href = theme === 'light'
      ? 'vendor/hljs-light.min.css'
      : 'vendor/hljs-dark.min.css';
  }
}

function escHtml(str) {
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

window.addEventListener('beforeunload', () => {
  if (socket.readyState === WebSocket.OPEN) {
    saveSessionToServer();
  }
});

function jsonStringifyEvent(type, content = {}) {
  return JSON.stringify({
    type,
    [typeof content === 'string' ? 'content' : 'data']: content,
  });
}

// ── Tree floating panel: drag + resize ─────────────────────────────
(function () {
  const panel  = document.getElementById('tree-view-panel');
  const header = panel.querySelector('.panel-header');
  const handle = document.getElementById('tree-resize-handle');

  // ── Drag ──────────────────────────────────────────────────────
  let dragActive = false;
  let dragOffX = 0, dragOffY = 0;

  header.addEventListener('mousedown', (e) => {
    // don't drag if clicking the close button
    if (e.target.closest('button')) return;
    dragActive = true;
    dragOffX = e.clientX - panel.offsetLeft;
    dragOffY = e.clientY - panel.offsetTop;
    e.preventDefault();
  });

  // ── Resize ────────────────────────────────────────────────────
  let resizeActive = false;
  let resizeStartX = 0, resizeStartY = 0;
  let resizeStartW = 0, resizeStartH = 0;

  handle.addEventListener('mousedown', (e) => {
    resizeActive = true;
    resizeStartX = e.clientX;
    resizeStartY = e.clientY;
    resizeStartW = panel.offsetWidth;
    resizeStartH = panel.offsetHeight;
    e.preventDefault();
    e.stopPropagation();  // don't trigger drag
  });

  // ── Shared mousemove / mouseup ─────────────────────────────────
  window.addEventListener('mousemove', (e) => {
    if (dragActive) {
      let newLeft = e.clientX - dragOffX;
      let newTop  = e.clientY - dragOffY;

      // keep panel inside viewport
      newLeft = Math.max(0, Math.min(newLeft, window.innerWidth  - panel.offsetWidth));
      newTop  = Math.max(0, Math.min(newTop,  window.innerHeight - panel.offsetHeight));

      panel.style.left = newLeft + 'px';
      panel.style.top  = newTop  + 'px';
    }

    if (resizeActive) {
      const newW = resizeStartW + (e.clientX - resizeStartX);
      const newH = resizeStartH + (e.clientY - resizeStartY);
      panel.style.width  = Math.max(280, newW) + 'px';
      panel.style.height = Math.max(200, newH) + 'px';
    }
  });

  window.addEventListener('mouseup', () => {
    dragActive   = false;
    resizeActive = false;
  });
})();