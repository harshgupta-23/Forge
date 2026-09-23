const rawWsUrl = (
  window.__FORGE_BACKEND_URL__ ||
  localStorage.getItem('forge_backend_url') ||
  'ws://localhost:8765/ws'
);
let BACKEND_WS_URL;
try {
  const parsed = new URL(rawWsUrl);
  if (!parsed.pathname || parsed.pathname === '/') {
    parsed.pathname = '/ws';
  }
  if (!parsed.searchParams.has('role')) {
    parsed.searchParams.set('role', 'main');
  }
  BACKEND_WS_URL = parsed.toString();
} catch (_) {
  BACKEND_WS_URL = rawWsUrl.includes('?') ? `${rawWsUrl}&role=main` : `${rawWsUrl}/ws?role=main`;
}
const socket = new WebSocket(BACKEND_WS_URL);

const logsDiv      = document.getElementById('logs');
const statusBar    = document.getElementById('agent-status-bar');
const userInput    = document.getElementById('user-input');
const sendBtn      = document.getElementById('send-btn');
const settingsPanel = document.getElementById('settings-panel');
const toggleSettings = document.getElementById('toggle-settings');
const closeSettings = document.getElementById('close-settings');
const btnNewSession = document.getElementById('btn-new-session');
const btnUndo      = document.getElementById('btn-undo');
const btnBranchPrev = document.getElementById('btn-branch-prev');
const btnSummarise = document.getElementById('btn-summarise');
const btnTreeView  = document.getElementById('btn-tree-view');

let latestTreeNodes = {};
let latestActiveNodeId = "node_root";
const treeViewPanel = document.getElementById('tree-view-panel');
const closeTreeView = document.getElementById('close-tree-view');
const btnDetachTree = document.getElementById('btn-detach-tree');
const treeContainer = document.getElementById('tree-container');
const btnFetchSession      = document.getElementById('btn-fetch-session');
const sessionPickerPanel   = document.getElementById('session-picker-panel');
const closeSessionPicker   = document.getElementById('close-session-picker');
const sessionListContainer = document.getElementById('session-list-container');
const btnStop = document.getElementById('btn-stop');
const tokens5hEl  = document.getElementById('tokens-5h');
const tokens24hEl = document.getElementById('tokens-24h');
const btnToggleSidebar = document.getElementById('btn-toggle-sidebar');
const appSidebar = document.getElementById('app-sidebar');
const dragDropOverlay = document.getElementById('drag-drop-overlay');
const btnAttachFile = document.getElementById('btn-attach-file');
const attachedChipsTray = document.getElementById('attached-chips-tray');
const unifiedConsole = document.getElementById('unified-console');
const activeBranchLabel = document.getElementById('active-branch-label');

async function openDetachedTreeWindow() {
  const activeSessionId = localStorage.getItem('forge_active_session_id') || '';
  const treeUrl = `tree.html${activeSessionId ? `?session_id=${encodeURIComponent(activeSessionId)}` : ''}`;

  // Tauri v2 desktop environment check
  if (window.__TAURI__ && window.__TAURI__.webviewWindow) {
    try {
      const { WebviewWindow } = window.__TAURI__.webviewWindow;
      const existing = await WebviewWindow.getByLabel('tree-view');
      if (existing) {
        await existing.show();
        await existing.setFocus();
        return;
      }

      const treeWin = new WebviewWindow('tree-view', {
        url: treeUrl,
        title: 'Forge — Conversation Branches',
        width: 1050,
        height: 750,
        minWidth: 600,
        minHeight: 400,
        resizable: true,
        center: true
      });

      treeWin.once('tauri://error', (e) => {
        console.warn('[tauri] Error opening WebviewWindow, falling back to popup:', e);
        window.open(treeUrl, 'ForgeTreeView', 'width=1050,height=750,resizable=yes');
      });
      return;
    } catch (err) {
      console.warn('[tauri] Error creating WebviewWindow:', err);
    }
  }

  // Standard browser window fallback
  const popup = window.open(treeUrl, 'ForgeTreeView', 'width=1050,height=750,resizable=yes');
  if (!popup || popup.closed || typeof popup.closed === 'undefined') {
    // Popup was blocked by browser, open in-page panel instead
    treeViewPanel.classList.remove('hidden');
    panX = 40;
    panY = 40;
    zoomScale = 1.0;
    updateTreeTransform();
    window.dispatchEvent(new Event('resize'));
  }
}

// ── Reusable SVG Icons (cross-platform, Linux-safe) ───────────────────────────
const ICONS = {
  CHECK: `<svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  GEAR: `<svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
  EDIT: `<svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`,
  TRASH: `<svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`,
  PLAY: `<svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>`,
  ZAP: `<svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
  CLIP: `<svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>`,
  ALERT: `<svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
  USER: `<svg class="icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
  BOT: `<svg class="icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></svg>`,
  EYE: `<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`,
  EYE_OFF: `<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`,
  CLOSE: `<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`
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

  const header = document.createElement('div');
  header.className = 'bubble-header';

  const label = document.createElement('span');
  label.className   = 'bubble-label';
  label.textContent = 'Agent: ';
  header.appendChild(label);

  const badge = document.createElement('span');
  badge.className = 'token-pill agent-token-pill agent-live-token-pill';
  badge.textContent = '~0 tok';
  header.appendChild(badge);

  const body = document.createElement('span');
  body.className = 'bubble-body';

  currentAgentBubble.appendChild(header);
  currentAgentBubble.appendChild(body);
  logsDiv.appendChild(currentAgentBubble);
  logsDiv.scrollTop = logsDiv.scrollHeight;
}

function appendToken(token) {
  if (!currentAgentBubble) startAgentBubble();
  currentAgentText += token;
  currentAgentBubble.querySelector('.bubble-body').textContent = currentAgentText;
  const liveBadge = currentAgentBubble.querySelector('.agent-live-token-pill');
  if (liveBadge) {
    const liveToks = Math.max(1, Math.floor(currentAgentText.length / 4));
    liveBadge.textContent = `~${liveToks.toLocaleString()} tok`;
  }
  logsDiv.scrollTop = logsDiv.scrollHeight;
}

function finaliseAgentBubble(agentTokens = null) {
  if (currentAgentBubble) {
    const body = currentAgentBubble.querySelector('.bubble-body');
    body.innerHTML = renderMarkdown(currentAgentText);  // swap textContent → rendered HTML
    const liveBadge = currentAgentBubble.querySelector('.agent-live-token-pill');
    if (liveBadge) {
      const finalToks = agentTokens || Math.max(1, Math.floor(currentAgentText.length / 4));
      liveBadge.textContent = `~${finalToks.toLocaleString()} tok`;
      liveBadge.classList.remove('agent-live-token-pill');
    }
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
function addToolRow(icon, text, className, tokens = null) {
  const row = document.createElement('div');
  row.className = `tool-row ${className}`;
  const iconSpan = `<span class="tool-icon">${icon}</span>`;
  const textSpan = `<span class="tool-text">${escHtml(text)}</span>`;
  let badgeSpan = '';
  if (tokens !== null && tokens !== undefined && Number(tokens) > 0) {
    badgeSpan = `<span class="token-pill tool-token-pill">~${Number(tokens).toLocaleString()} tok</span>`;
  }
  row.innerHTML = `${iconSpan}${textSpan}${badgeSpan}`;
  logsDiv.appendChild(row);
  logsDiv.scrollTop = logsDiv.scrollHeight;
}

// ── Tree View Drawing ──────────────────────────────────────────────────────────
function renderChatHistory(pathMessages) {
  logsDiv.innerHTML = "";
  
  pathMessages.forEach(msg => {
    if (msg.type === "human") {
      appendOutputMessage(msg.content, 'user-query', 'You: ', msg.tokens);
    } else if (msg.type === "ai") {
      if (msg.content && typeof msg.content === 'string') {
        const clean = msg.content.replace(/<tool_call>[\s\S]*?<\/tool_call>/gi, '').trim();
        if (clean) {
          appendOutputMessage(clean, 'agent-response', 'Agent: ', msg.tokens);
        }
      }
    } else if (msg.type === "tool") {
      const firstLine = msg.content ? msg.content.split('\n')[0].trim() : "";
      const summary = firstLine.substring(0, 80) + (firstLine.length > 80 ? '…' : '');
      const toks = msg.tokens || (msg.content ? Math.max(1, Math.floor(msg.content.length / 4)) : 0);
      addToolRow(ICONS.CHECK, `${msg.name} → ${summary}`, 'tool-done', toks);
    }
  });
  
  logsDiv.scrollTop = logsDiv.scrollHeight;
  const terminalChat = document.getElementById('terminal-chat');
  if (terminalChat) terminalChat.scrollTop = terminalChat.scrollHeight;
}

function renderTreeView(nodes, rootId, activeNodeId) {
  latestTreeNodes = nodes || {};
  latestActiveNodeId = activeNodeId || "node_root";

  if (activeBranchLabel) {
    const nodeLabel = latestTreeNodes[latestActiveNodeId]?.label || latestActiveNodeId;
    activeBranchLabel.textContent = latestActiveNodeId === "node_root" ? "main" : (nodeLabel.length > 20 ? nodeLabel.slice(0, 18) + '…' : nodeLabel);
  }

  if (btnBranchPrev) {
    const canBranch = Boolean(latestActiveNodeId && latestActiveNodeId !== "node_root" && latestTreeNodes[latestActiveNodeId]?.parent_id);
    btnBranchPrev.disabled = !canBranch;
    btnBranchPrev.style.opacity = canBranch ? '1' : '0.45';
  }

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

    if (node.is_pruned) {
      card.classList.add('is-pruned');
      const prunedBadge = document.createElement('span');
      prunedBadge.className = 'node-pruned-badge';
      prunedBadge.textContent = 'Pruned';
      prunedBadge.title = 'Dead-end branch pruned from active context (click to revive)';
      meta.appendChild(prunedBadge);
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

    if (node.type !== "root") {
      const tokenBox = document.createElement('div');
      tokenBox.className = 'node-token-breakdown';

      let uTok = (node.tokens && node.tokens.user) || 0;
      let tTok = (node.tokens && node.tokens.tools) || 0;
      let aTok = (node.tokens && node.tokens.agent) || 0;
      let totTok = (node.tokens && node.tokens.total) || 0;

      if (!node.tokens) {
        uTok = node.user_message ? Math.max(1, Math.floor((node.user_message.content || '').length / 4)) : 0;
        tTok = node.tool_results ? node.tool_results.reduce((acc, r) => acc + (r.tokens || Math.max(1, Math.floor((r.content || '').length / 4))), 0) : 0;
        aTok = node.agent_message ? Math.max(1, Math.floor((node.agent_message.content || '').length / 4)) : 0;
        totTok = uTok + tTok + aTok;
      }

      tokenBox.innerHTML = `
        <span class="node-token-total" title="Total Turn Tokens">~${totTok.toLocaleString()} tok</span>
        <span class="node-token-detail">
          <span title="User prompt tokens">${ICONS.USER} ${uTok}</span>
          ${tTok > 0 ? `<span title="Tool tokens">${ICONS.GEAR} ${tTok}</span>` : ''}
          <span title="Agent output tokens">${ICONS.BOT} ${aTok}</span>
        </span>
      `;
      card.appendChild(tokenBox);
    }
    
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

    if (node.type !== "root") {
      const undoBtn = document.createElement('button');
      undoBtn.className = 'node-btn node-btn-delete';
      undoBtn.innerHTML = `${ICONS.TRASH} Undo`;
      undoBtn.title = 'Remove this turn and its side branch from history';
      undoBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (confirm('Remove this node and its entire side branch from history?')) {
          socket.send(JSON.stringify({
            type: "undo",
            data: { node_id: nodeId }
          }));
        }
      });
      actions.appendChild(undoBtn);
    }

    card.appendChild(actions);
    
    card.addEventListener('click', (e) => {
      e.stopPropagation();
      if (nodeId !== latestActiveNodeId) {
        latestActiveNodeId = nodeId;
        // Optimistically update card styling
        document.querySelectorAll('#tree-container .tree-node-card').forEach(c => {
          c.classList.remove('active-tip');
        });
        card.classList.add('active-tip');

        // Update active branch badge in header
        if (activeBranchLabel) {
          const nodeLabel = latestTreeNodes[nodeId]?.label || nodeId;
          activeBranchLabel.textContent = nodeId === "node_root" ? "main" : (nodeLabel.length > 20 ? nodeLabel.slice(0, 18) + '…' : nodeLabel);
        }

        if (btnBranchPrev) {
          const canBranch = Boolean(nodeId && nodeId !== "node_root" && latestTreeNodes[nodeId]?.parent_id);
          btnBranchPrev.disabled = !canBranch;
          btnBranchPrev.style.opacity = canBranch ? '1' : '0.45';
        }

        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({
            type: "set_active",
            content: nodeId
          }));
        }
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

    const activeStoredId = localStorage.getItem('forge_active_session_id');
    if (activeStoredId && s.session_id === activeStoredId) {
      item.classList.add('active-session');
    }

    // Click handler for the card itself (loads the session)
    item.addEventListener('click', () => {
      document.querySelectorAll('#session-list-container .tree-node-card').forEach(c => c.classList.remove('active-session'));
      item.classList.add('active-session');
      localStorage.setItem('forge_active_session_id', s.session_id);
      socket.send(JSON.stringify({ type: 'load_session', data: { session_id: s.session_id } }));
      if (sessionPickerPanel) sessionPickerPanel.classList.add('hidden');
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
  if (window.__TAURI__ && window.__TAURI__.webviewWindow) {
    openDetachedTreeWindow();
    return;
  }
  treeViewPanel.classList.toggle('hidden');
  settingsPanel.classList.add('hidden');
  if (!treeViewPanel.classList.contains('hidden')) {
    // Request fresh tree data from backend
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(jsonStringifyEvent("get_config"));
    }
    if (latestTreeNodes && Object.keys(latestTreeNodes).length > 0) {
      renderTreeView(latestTreeNodes, "node_root", latestActiveNodeId);
    }
    // Reset zoom and center view slightly on open
    panX = 40;
    panY = 40;
    zoomScale = 1.0;
    updateTreeTransform();
    window.dispatchEvent(new Event('resize'));
  }
});

if (btnDetachTree) {
  btnDetachTree.addEventListener('click', () => {
    treeViewPanel.classList.add('hidden');
    openDetachedTreeWindow();
  });
}

closeTreeView.addEventListener('click', () => {
  treeViewPanel.classList.add('hidden');
});

closeSettings.addEventListener('click', () => {
  settingsPanel.classList.add('hidden');
});

btnFetchSession.addEventListener('click', () => {
  socket.send(JSON.stringify({ type: 'list_sessions' }));
  if (sessionPickerPanel && !sessionPickerPanel.classList.contains('hidden')) {
    sessionPickerPanel.classList.add('hidden');
  }
});

if (closeSessionPicker) {
  closeSessionPicker.addEventListener('click', () => {
    if (sessionPickerPanel) sessionPickerPanel.classList.add('hidden');
  });
}

socket.onopen = () => {
  socket.send(jsonStringifyEvent("get_config"));
  socket.send(JSON.stringify({ type: 'get_token_usage' }));
  socket.send(JSON.stringify({ type: 'list_sessions' }));
};

socket.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  if (msg.type === "config") {
    document.getElementById('cfg-key').value   = msg.data.API_KEY  || '';
    document.getElementById('cfg-base').value  = msg.data.API_BASE || '';
    document.getElementById('cfg-model').value = msg.data.MODEL    || '';

    const modelPlannerEl = document.getElementById('cfg-model-planner');
    if (modelPlannerEl) modelPlannerEl.value = msg.data.MODEL_PLANNER || '';

    const modelSummarizerEl = document.getElementById('cfg-model-summarizer');
    if (modelSummarizerEl) modelSummarizerEl.value = msg.data.MODEL_SUMMARIZER || '';

    const modelRerankerEl = document.getElementById('cfg-model-reranker');
    if (modelRerankerEl) modelRerankerEl.value = msg.data.MODEL_RERANKER || '';

    const keyPlannerEl = document.getElementById('cfg-key-planner');
    if (keyPlannerEl) keyPlannerEl.value = msg.data.API_KEY_PLANNER || '';

    const basePlannerEl = document.getElementById('cfg-base-planner');
    if (basePlannerEl) basePlannerEl.value = msg.data.API_BASE_PLANNER || '';

    const keySummarizerEl = document.getElementById('cfg-key-summarizer');
    if (keySummarizerEl) keySummarizerEl.value = msg.data.API_KEY_SUMMARIZER || '';

    const baseSummarizerEl = document.getElementById('cfg-base-summarizer');
    if (baseSummarizerEl) baseSummarizerEl.value = msg.data.API_BASE_SUMMARIZER || '';

    const keyRerankerEl = document.getElementById('cfg-key-reranker');
    if (keyRerankerEl) keyRerankerEl.value = msg.data.API_KEY_RERANKER || '';

    const baseRerankerEl = document.getElementById('cfg-base-reranker');
    if (baseRerankerEl) baseRerankerEl.value = msg.data.API_BASE_RERANKER || '';

    const modelTopicGateEl = document.getElementById('cfg-model-topic-gate');
    if (modelTopicGateEl) modelTopicGateEl.value = msg.data.MODEL_TOPIC_GATE || '';

    const keyTopicGateEl = document.getElementById('cfg-key-topic-gate');
    if (keyTopicGateEl) keyTopicGateEl.value = msg.data.API_KEY_TOPIC_GATE || '';

    const baseTopicGateEl = document.getElementById('cfg-base-topic-gate');
    if (baseTopicGateEl) baseTopicGateEl.value = msg.data.API_BASE_TOPIC_GATE || '';

    document.getElementById('cfg-dir').value   = msg.data.AGENT_WORK_DIR  || '';
    document.getElementById('cfg-db').value    = msg.data.DATABASE_URL    || '';
    document.getElementById('cfg-theme').value = msg.data.THEME           || 'dark';
    applyTheme(msg.data.THEME);
    if (msg.data.THEME) {
      localStorage.setItem('forge_theme', msg.data.THEME);
    }
    updateModelPlaceholders();
  }
  else if (msg.type === "token_usage_windows") {
    tokens5hEl.textContent  = `5h: ~${Number(msg.last_5h).toLocaleString()}`;
    tokens24hEl.textContent = `24h: ~${Number(msg.last_24h).toLocaleString()}`;
  }
  else if (msg.type === "chat_history") {
    renderChatHistory(msg.messages);
  }
  else if (msg.type === "tree_data") {
    if (msg.session_id) {
      localStorage.setItem('forge_active_session_id', msg.session_id);
    }
    renderTreeView(msg.nodes, msg.root_id, msg.active_node_id);
  }
  else if (msg.type === "node_added") {
    if (!latestTreeNodes) latestTreeNodes = {};
    if (msg.node && msg.node.id) {
      latestTreeNodes[msg.node.id] = msg.node;
      const parentId = msg.node.parent_id;
      if (parentId && latestTreeNodes[parentId]) {
        if (!latestTreeNodes[parentId].children_ids) {
          latestTreeNodes[parentId].children_ids = [];
        }
        if (!latestTreeNodes[parentId].children_ids.includes(msg.node.id)) {
          latestTreeNodes[parentId].children_ids.push(msg.node.id);
        }
      }
    }
    renderTreeView(latestTreeNodes, "node_root", msg.active_node_id || msg.node?.id);
  }
  else if (msg.type === "session_switched") {
    if (msg.session_id) {
      localStorage.setItem('forge_active_session_id', msg.session_id);
    }
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
  else if (msg.type === "indexing_progress") {
    statusBar.textContent = `${msg.filename}: ${msg.message} (${msg.progress_pct}%)`;
    if (msg.step === "indexed") {
      appendOutputMessage(`${ICONS.CHECK} Indexed <strong>${escHtml(msg.filename)}</strong> (${msg.chunks_count} chunks) into knowledge vector store`, 'status-msg');
    } else if (msg.step === "error") {
      appendOutputMessage(`${ICONS.ALERT} ${escHtml(msg.message)}`, 'error-response');
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
    addToolRow(ICONS.CHECK, msg.content, 'tool-done', msg.tokens);
  }
  else if (msg.type === "token") {
    statusBar.textContent = '';
    appendToken(msg.content);
  }
  else if (msg.type === "done") {
    finaliseAgentBubble();
    setGenerating(false);
    statusBar.textContent = '';
    socket.send(JSON.stringify({ type: 'list_sessions' }));
  }
  else if (msg.type === "token_count") {
    sessionTotalTokens = msg.content;
    if (msg.breakdown) {
      const b = msg.breakdown;
      const savingsHtml = b.pruned_savings > 0 ? ` <span class="pruned-savings-pill" title="Tokens saved via dynamic context pruning">Saved ~${Number(b.pruned_savings).toLocaleString()} tok</span>` : '';
      statusBar.innerHTML = `<span>Context: ~${Number(b.context_total).toLocaleString()} tok</span>${savingsHtml} <span class="turn-token-summary" title="User: ${b.user} | Tools: ${b.tools} | Agent: ${b.agent}">(Turn: ~${b.turn_total.toLocaleString()} tok &bull; You: ${b.user} | Tools: ${b.tools} | Agent: ${b.agent})</span>`;
      
      const divider = document.createElement('div');
      divider.className = 'turn-summary-divider';
      const divSavings = b.pruned_savings > 0 ? ` &bull; Saved ~${Number(b.pruned_savings).toLocaleString()} tok` : '';
      divider.innerHTML = `Turn &bull; ~${b.turn_total.toLocaleString()} tok (You: ~${b.user} &bull; Tools: ~${b.tools} &bull; Agent: ~${b.agent}${divSavings})`;
      logsDiv.appendChild(divider);
      logsDiv.scrollTop = logsDiv.scrollHeight;
    } else {
      statusBar.textContent = `Context: ~${Number(msg.content).toLocaleString()} tokens`;
    }
  }
  else if (msg.type === "branch_prompt") {
    setGenerating(false);
    statusBar.textContent = 'Topic shift detected. Please choose how to proceed.';
    renderBranchPrompt(msg.topic, msg.reason, msg.user_text);
  }
  else if (msg.type === "error") {
    finaliseAgentBubble();
    appendOutputMessage(`${ICONS.ALERT} ${msg.content}`, 'error-response');
    setGenerating(false);
    statusBar.textContent = '';
  }
};

function renderBranchPrompt(topic, reason, userText) {
  const card = document.createElement('div');
  card.className = 'branch-prompt-card';
  card.innerHTML = `
    <div class="branch-prompt-header">
      <span class="branch-prompt-icon">${ICONS.ZAP}</span>
      <span class="branch-prompt-title">Topic Shift Detected: <strong>${escHtml(topic || 'New Topic')}</strong></span>
    </div>
    <div class="branch-prompt-reason">${escHtml(reason || 'The query appears to switch to an unrelated topic from the previous turn.')}</div>
    <div class="branch-prompt-text">Would you like to branch from the previous turn, or continue in this branch?</div>
    <div class="branch-prompt-buttons">
      <button class="branch-btn branch-btn-fork" id="btn-branch-fork">
        <svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>
        Branch from Previous Turn
      </button>
      <button class="branch-btn branch-btn-continue" id="btn-branch-continue">
        Continue in Current Branch &rarr;
      </button>
    </div>
  `;

  const forkBtn = card.querySelector('#btn-branch-fork');
  const contBtn = card.querySelector('#btn-branch-continue');

  forkBtn.addEventListener('click', () => {
    forkBtn.disabled = true;
    contBtn.disabled = true;
    card.classList.add('answered');
    forkBtn.classList.add('selected');
    statusBar.textContent = 'Branching from previous turn…';
    btnStop.classList.remove('hidden');
    socket.send(JSON.stringify({ type: 'branch_decision', decision: 'branch' }));
  });

  contBtn.addEventListener('click', () => {
    forkBtn.disabled = true;
    contBtn.disabled = true;
    card.classList.add('answered');
    contBtn.classList.add('selected');
    statusBar.textContent = 'Continuing in current branch…';
    btnStop.classList.remove('hidden');
    socket.send(JSON.stringify({ type: 'branch_decision', decision: 'continue' }));
  });

  logsDiv.appendChild(card);
  logsDiv.scrollTop = logsDiv.scrollHeight;
}

// ── Settings Sidebar & Modal Controllers ─────────────────────────────────────────
function updateModelPlaceholders() {
  const primaryModel = (document.getElementById('cfg-model')?.value || '').trim() || 'gemma-4-26b-a4b-it';
  const plannerEl = document.getElementById('cfg-model-planner');
  if (plannerEl) {
    plannerEl.placeholder = `Inherit from primary (${primaryModel})`;
  }
  const summarizerEl = document.getElementById('cfg-model-summarizer');
  if (summarizerEl) {
    summarizerEl.placeholder = `Inherit from primary (${primaryModel})`;
  }
  const rerankerEl = document.getElementById('cfg-model-reranker');
  if (rerankerEl) {
    const plannerModel = (plannerEl?.value || '').trim() || primaryModel;
    rerankerEl.placeholder = `Inherit from planner (${plannerModel})`;
  }
  const topicGateEl = document.getElementById('cfg-model-topic-gate');
  if (topicGateEl) {
    const plannerModel = (plannerEl?.value || '').trim() || primaryModel;
    topicGateEl.placeholder = `Inherit from planner (${plannerModel})`;
  }
}

// Live update placeholders when typing in model fields
document.getElementById('cfg-model')?.addEventListener('input', updateModelPlaceholders);
document.getElementById('cfg-model-planner')?.addEventListener('input', updateModelPlaceholders);
document.getElementById('cfg-model-topic-gate')?.addEventListener('input', updateModelPlaceholders);

// Tab switching inside settings dialog
document.querySelectorAll('.settings-tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.settings-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.settings-pane').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const targetId = `pane-${btn.dataset.tab}`;
    const pane = document.getElementById(targetId);
    if (pane) pane.classList.add('active');
  });
});

// Quick provider presets — NEVER clobbers existing API key
const PROVIDER_PRESETS = {
  gemini: {
    name: 'Google Gemini',
    base: 'https://generativelanguage.googleapis.com/v1beta/openai/',
    model: 'gemma-4-26b-a4b-it',
    planner: 'gemini-1.5-flash',
    summarizer: 'gemini-1.5-flash',
    reranker: 'gemini-1.5-flash',
    topic_gate: 'gemini-1.5-flash'
  },
  claude: {
    name: 'Anthropic Claude',
    base: 'https://openrouter.ai/api/v1',
    model: 'anthropic/claude-3.5-sonnet',
    planner: 'anthropic/claude-3.5-haiku',
    summarizer: 'anthropic/claude-3.5-haiku',
    reranker: 'anthropic/claude-3.5-haiku',
    topic_gate: 'anthropic/claude-3.5-haiku'
  },
  openai: {
    name: 'OpenAI GPT-4o',
    base: 'https://api.openai.com/v1',
    model: 'gpt-4o',
    planner: 'gpt-4o-mini',
    summarizer: 'gpt-4o-mini',
    reranker: 'gpt-4o-mini',
    topic_gate: 'gpt-4o-mini'
  },
  ollama: {
    name: 'Local Ollama',
    base: 'http://localhost:11434/v1',
    model: 'llama3.1:8b',
    planner: 'qwen2.5:3b',
    summarizer: 'qwen2.5:3b',
    reranker: 'qwen2.5:3b',
    topic_gate: 'qwen2.5:3b'
  }
};

document.querySelectorAll('.preset-chip').forEach(chip => {
  chip.addEventListener('click', () => {
    const preset = PROVIDER_PRESETS[chip.dataset.preset];
    if (!preset) return;

    // Overwrite only models and base URL — API Key is explicitly preserved
    const baseEl = document.getElementById('cfg-base');
    const modelEl = document.getElementById('cfg-model');
    const plannerEl = document.getElementById('cfg-model-planner');
    const summarizerEl = document.getElementById('cfg-model-summarizer');
    const rerankerEl = document.getElementById('cfg-model-reranker');
    const topicGateEl = document.getElementById('cfg-model-topic-gate');

    if (baseEl) baseEl.value = preset.base;
    if (modelEl) modelEl.value = preset.model;
    if (plannerEl) plannerEl.value = preset.planner;
    if (summarizerEl) summarizerEl.value = preset.summarizer;
    if (rerankerEl) rerankerEl.value = preset.reranker;
    if (topicGateEl) topicGateEl.value = preset.topic_gate || preset.planner;

    updateModelPlaceholders();

    const statusEl = document.getElementById('settings-status');
    if (statusEl) {
      statusEl.textContent = `Applied ${preset.name} template.`;
      setTimeout(() => { if (statusEl.textContent.includes('Applied')) statusEl.textContent = ''; }, 3500);
    }
  });
});

// Password visibility toggle for API key
const toggleKeyBtn = document.getElementById('toggle-key-visibility');
if (toggleKeyBtn) {
  toggleKeyBtn.addEventListener('click', () => {
    const keyInput = document.getElementById('cfg-key');
    if (!keyInput) return;
    if (keyInput.type === 'password') {
      keyInput.type = 'text';
      toggleKeyBtn.innerHTML = ICONS.EYE_OFF;
      toggleKeyBtn.title = "Hide API Key";
    } else {
      keyInput.type = 'password';
      toggleKeyBtn.innerHTML = ICONS.EYE;
      toggleKeyBtn.title = "Show API Key";
    }
  });
}

// Cancel & Backdrop dismiss
const cancelSettingsBtn = document.getElementById('cancel-settings');
if (cancelSettingsBtn) {
  cancelSettingsBtn.addEventListener('click', () => {
    settingsPanel.classList.add('hidden');
  });
}

// Click on backdrop scrim outside dialog closes modal
settingsPanel.addEventListener('click', (e) => {
  if (e.target === settingsPanel) {
    settingsPanel.classList.add('hidden');
  }
});

// Escape key dismisses modal
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !settingsPanel.classList.contains('hidden')) {
    settingsPanel.classList.add('hidden');
  }
});

// Save settings handler
document.getElementById('save-settings').addEventListener('click', () => {
  const payload = {
    API_KEY:             document.getElementById('cfg-key').value.trim(),
    API_BASE:            document.getElementById('cfg-base').value.trim(),
    MODEL:               document.getElementById('cfg-model').value.trim(),
    MODEL_PLANNER:       document.getElementById('cfg-model-planner')?.value.trim() || '',
    MODEL_SUMMARIZER:    document.getElementById('cfg-model-summarizer')?.value.trim() || '',
    MODEL_RERANKER:      document.getElementById('cfg-model-reranker')?.value.trim() || '',
    MODEL_TOPIC_GATE:    document.getElementById('cfg-model-topic-gate')?.value.trim() || '',
    API_KEY_PLANNER:     document.getElementById('cfg-key-planner')?.value.trim() || '',
    API_BASE_PLANNER:    document.getElementById('cfg-base-planner')?.value.trim() || '',
    API_KEY_SUMMARIZER:  document.getElementById('cfg-key-summarizer')?.value.trim() || '',
    API_BASE_SUMMARIZER: document.getElementById('cfg-base-summarizer')?.value.trim() || '',
    API_KEY_RERANKER:    document.getElementById('cfg-key-reranker')?.value.trim() || '',
    API_BASE_RERANKER:   document.getElementById('cfg-base-reranker')?.value.trim() || '',
    API_KEY_TOPIC_GATE:  document.getElementById('cfg-key-topic-gate')?.value.trim() || '',
    API_BASE_TOPIC_GATE: document.getElementById('cfg-base-topic-gate')?.value.trim() || '',
    AGENT_WORK_DIR:      document.getElementById('cfg-dir').value.trim(),
    DATABASE_URL:        document.getElementById('cfg-db').value.trim(),
    THEME:               document.getElementById('cfg-theme').value,
  };
  socket.send(jsonStringifyEvent("save_config", payload));
  applyTheme(payload.THEME);
  if (payload.THEME) {
    localStorage.setItem('forge_theme', payload.THEME);
  }
  const statusEl = document.getElementById('settings-status');
  if (statusEl) {
    statusEl.textContent = 'Configuration saved and applied.';
    setTimeout(() => { statusEl.textContent = ''; }, 2500);
  }
  settingsPanel.classList.add('hidden');
  // Request fresh config echo so UI fields stay in sync with what was persisted
  setTimeout(() => socket.send(jsonStringifyEvent("get_config")), 300);
});

// ── Generation State Management ──────────────────────────────────────────────
function setGenerating(isGenerating) {
  if (isGenerating) {
    btnStop.classList.remove('hidden');
    sendBtn.classList.add('hidden');
    if (unifiedConsole) unifiedConsole.classList.add('generating');
  } else {
    btnStop.classList.add('hidden');
    sendBtn.classList.remove('hidden');
    if (unifiedConsole) unifiedConsole.classList.remove('generating');
  }
}

// ── Auto-Resizing Textarea & Input Handling ─────────────────────────────────
function autoResizeUserInput() {
  if (!userInput) return;
  userInput.style.height = 'auto';
  const newHeight = Math.min(userInput.scrollHeight, 180);
  userInput.style.height = `${newHeight}px`;
  
  // Auto-scroll chat so messages are never masked behind expanding console
  const chatCanvas = document.getElementById('terminal-chat');
  if (chatCanvas) {
    chatCanvas.scrollTop = chatCanvas.scrollHeight;
  }
}

userInput.addEventListener('input', autoResizeUserInput);
userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    dispatchMessage();
  }
});

// ── Send message ─────────────────────────────────────────────────────────────
sendBtn.addEventListener('click', dispatchMessage);
btnStop.addEventListener('click', () => {
  socket.send(JSON.stringify({ type: 'stop_generation' }));
  setGenerating(false);
});

function dispatchMessage() {
  const txt = userInput.value.trim();
  if (!txt) return;
  const userToks = Math.max(1, Math.floor(txt.length / 4));
  appendOutputMessage(txt, 'user-query', 'You: ', userToks);
  socket.send(jsonStringifyEvent("user_message", txt));
  setGenerating(true);
  userInput.value = "";
  userInput.style.height = 'auto';

  // Clear attached chips tray for fresh turn
  if (attachedChipsTray) {
    attachedChipsTray.innerHTML = '';
  }
}

// ── Sidebar Toggle Controls ──────────────────────────────────────────────────
if (btnToggleSidebar && appSidebar) {
  btnToggleSidebar.addEventListener('click', () => {
    appSidebar.classList.toggle('collapsed');
  });
}

window.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
    e.preventDefault();
    if (appSidebar) appSidebar.classList.toggle('collapsed');
  }
});

// ── File Attachment & Inline Chips ───────────────────────────────────────────
const filePickerInput = document.getElementById('file-picker-input');
const recentlyAttached = new Set();

function addAttachedChip(name, path) {
  if (!attachedChipsTray) return;
  const chip = document.createElement('span');
  chip.className = 'attached-chip';
  chip.innerHTML = `
    <svg class="icon" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
    <span>${escHtml(name)}</span>
    <button type="button" class="attached-chip-remove" title="Remove attachment">×</button>
  `;
  chip.querySelector('.attached-chip-remove').addEventListener('click', () => {
    chip.remove();
  });
  attachedChipsTray.appendChild(chip);
}

function attachFile(name, path) {
  if (!name || !path) return;
  const key = `${name}::${path}`;
  if (recentlyAttached.has(key)) return;
  recentlyAttached.add(key);
  setTimeout(() => recentlyAttached.delete(key), 1500);

  if (socket.readyState !== WebSocket.OPEN) {
    appendOutputMessage(`${ICONS.ALERT} WebSocket not connected.`, 'error-response');
    return;
  }
  socket.send(JSON.stringify({ type: 'attach_file', name, path }));
  appendOutputMessage(`${ICONS.CLIP} Attaching: ${name}`, 'status-msg');
  addAttachedChip(name, path);
}

if (btnAttachFile && filePickerInput) {
  btnAttachFile.addEventListener('click', () => {
    filePickerInput.click();
  });
  filePickerInput.addEventListener('change', () => {
    if (filePickerInput.files && filePickerInput.files.length > 0) {
      handleFiles(filePickerInput.files);
      filePickerInput.value = '';
    }
  });
}

async function handleFiles(files) {
  if (!files || files.length === 0) return;
  for (const file of files) {
    if (file.path) {
      attachFile(file.name, file.path);
      continue;
    }
    // Fallback: Upload file to backend /api/upload to obtain local absolute path
    try {
      appendOutputMessage(`${ICONS.CLIP} Uploading ${file.name}...`, 'status-msg');
      const base64 = await readFileAsBase64(file);
      const res = await fetch('http://localhost:8765/api/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: file.name, content_base64: base64 })
      });
      if (!res.ok) {
        throw new Error(`Upload failed: ${res.statusText}`);
      }
      const data = await res.json();
      attachFile(data.name, data.path);
    } catch (err) {
      appendOutputMessage(`${ICONS.ALERT} Failed to upload ${file.name}: ${err.message}`, 'error-response');
    }
  }
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const res = reader.result;
      const commaIdx = res.indexOf(',');
      resolve(commaIdx >= 0 ? res.slice(commaIdx + 1) : res);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// ── Full-Window Frosted Drag and Drop Overlay ─────────────────────────────────
let dragCounter = 0;

function showDragOverlay() {
  if (dragDropOverlay) dragDropOverlay.classList.remove('hidden');
}

function hideDragOverlay() {
  if (dragDropOverlay) dragDropOverlay.classList.add('hidden');
}

// HTML5 Drag and Drop listeners with dragCounter & pointer-events:none on children
window.addEventListener('dragenter', (e) => {
  e.preventDefault();
  e.stopPropagation();
  dragCounter++;
  showDragOverlay();
}, false);

window.addEventListener('dragover', (e) => {
  e.preventDefault();
  e.stopPropagation();
}, false);

window.addEventListener('dragleave', (e) => {
  e.preventDefault();
  e.stopPropagation();
  dragCounter--;
  if (dragCounter <= 0) {
    dragCounter = 0;
    hideDragOverlay();
  }
}, false);

window.addEventListener('drop', (e) => {
  e.preventDefault();
  e.stopPropagation();
  dragCounter = 0;
  hideDragOverlay();
  if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
    handleFiles(e.dataTransfer.files);
  }
}, false);

// Tauri Native File Drop (supports Tauri v2 window events)
function setupTauriFileDrop() {
  if (!window.__TAURI__) return;

  if (window.__TAURI__.event && typeof window.__TAURI__.event.listen === 'function') {
    try {
      window.__TAURI__.event.listen('tauri://drag-enter', () => {
        showDragOverlay();
      });
      window.__TAURI__.event.listen('tauri://drag-over', () => {
        showDragOverlay();
      });
      window.__TAURI__.event.listen('tauri://drag-leave', () => {
        hideDragOverlay();
      });
      window.__TAURI__.event.listen('tauri://drag-drop', (event) => {
        hideDragOverlay();
        const paths = event.payload?.paths || (Array.isArray(event.payload) ? event.payload : []);
        paths.forEach(filePath => {
          const fileName = filePath.split(/[\\/]/).pop();
          attachFile(fileName, filePath);
        });
      });
    } catch (err) {
      console.warn('Failed to register window.__TAURI__.event drag listeners:', err);
    }
  }

  try {
    const win = window.__TAURI__.webviewWindow?.getCurrentWebviewWindow?.();
    if (win && typeof win.onDragDropEvent === 'function') {
      win.onDragDropEvent((event) => {
        const type = event?.payload?.type;
        if (type === 'drop') {
          hideDragOverlay();
          const paths = event.payload?.paths || [];
          paths.forEach(filePath => {
            const fileName = filePath.split(/[\\/]/).pop();
            attachFile(fileName, filePath);
          });
        } else if (type === 'enter' || type === 'over') {
          showDragOverlay();
        } else if (type === 'leave' || type === 'cancel') {
          hideDragOverlay();
        }
      });
    }
  } catch (err) {
    console.warn('Failed to register webviewWindow.onDragDropEvent:', err);
  }
}

setupTauriFileDrop();

// ── Absolute path attach ─────────────────────────────────────────────────────
const attachPathBtn = document.getElementById('attach-path-btn');
const pathInput = document.getElementById('path-input');

if (attachPathBtn) {
  attachPathBtn.addEventListener('click', attachPath);
}
if (pathInput) {
  pathInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') attachPath();
  });
}

function attachPath() {
  if (!pathInput) return;
  const path = pathInput.value.trim();
  if (!path) return;
  const name = path.split(/[\\/]/).pop();
  attachFile(name, path);
  pathInput.value = '';
}

// ── History controls ───────────────────────────────────────────────────────
btnNewSession.addEventListener('click', () => {
  socket.send(JSON.stringify({ type: 'clear' }));
});

btnUndo.addEventListener('click', () => {
  if (!confirm('Remove active turn and its side branch from history?')) return;
  socket.send(JSON.stringify({ type: 'undo' }));
});

if (btnBranchPrev) {
  btnBranchPrev.addEventListener('click', () => {
    if (!latestActiveNodeId || latestActiveNodeId === 'node_root') {
      statusBar.textContent = 'Already at session root.';
      return;
    }
    const curr = latestTreeNodes[latestActiveNodeId];
    if (!curr || !curr.parent_id) {
      statusBar.textContent = 'No previous turn found.';
      return;
    }
    socket.send(JSON.stringify({
      type: 'set_active',
      content: curr.parent_id
    }));
    statusBar.textContent = 'Switched to previous turn. New messages will branch from here.';
  });
}

btnSummarise.addEventListener('click', () => {
  if (!confirm('Summarise history to save tokens? This sends history to the LLM once.')) return;
  socket.send(JSON.stringify({ type: 'summarise' }));
  statusBar.textContent = 'Summarising history…';
});

// ── Helpers ────────────────────────────────────────────────────────────────────
function appendOutputMessage(text, className, labelText = "", tokens = null) {
  const el = document.createElement('div');
  el.className  = `msg-bubble ${className}`;
  if (labelText) {
    const header = document.createElement('div');
    header.className = 'bubble-header';

    const label = document.createElement('span');
    label.className   = 'bubble-label';
    label.textContent = labelText;
    header.appendChild(label);

    const toks = tokens !== null && tokens !== undefined ? Number(tokens) : (text ? Math.max(1, Math.floor(text.length / 4)) : 0);
    if (toks > 0) {
      const badge = document.createElement('span');
      badge.className = `token-pill ${className === 'user-query' ? 'user-token-pill' : 'agent-token-pill'}`;
      badge.textContent = `~${toks.toLocaleString()} tok`;
      header.appendChild(badge);
    }
    el.appendChild(header);

    const body = document.createElement('span');
    body.className    = 'bubble-body';
    // Agent responses get markdown rendering; user input stays as plain text (XSS safety)
    if (className === 'agent-response') {
      body.innerHTML = renderMarkdown(text);
    } else {
      body.textContent = text;
    }
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