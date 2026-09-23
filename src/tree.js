// ── Standalone Tree View Controller ──────────────────────────────────────────
const ICONS = {
  PLAY: `<svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>`,
  EDIT: `<svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>`,
  ZAP:  `<svg class="icon" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
  GEAR: `<svg class="icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
  USER: `<svg class="icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
  BOT:  `<svg class="icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></svg>`,
  TRASH: `<svg class="icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`
};

function escHtml(str) {
  return (str || '').replace(/[&<>"']/g, m => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  })[m]);
}

// ── DOM References ────────────────────────────────────────────────────────────
const treeContainer = document.getElementById('tree-container');
const sessionBadge = document.getElementById('tree-session-badge');
const statusDot = document.getElementById('tree-status-indicator');
const zoomValueEl = document.getElementById('zoom-value');
const btnZoomIn = document.getElementById('btn-zoom-in');
const btnZoomOut = document.getElementById('btn-zoom-out');
const btnZoomReset = document.getElementById('btn-zoom-reset');
const btnTreeBranchPrev = document.getElementById('btn-tree-branch-prev');

// ── State ─────────────────────────────────────────────────────────────────────
let socket = null;
let currentSessionId = null;
let currentNodes = null;
let currentRootId = null;
let currentActiveNodeId = null;
let reconnectTimer = null;

let panX = 60;
let panY = 60;
let zoomScale = 1.0;
let isDragging = false;
let startX = 0;
let startY = 0;
let currentResizeListener = null;

// ── Theme Handling ────────────────────────────────────────────────────────────
function applyTheme(theme) {
  const isLight = theme === 'light';
  document.body.classList.toggle('light-theme', isLight);
  document.body.classList.toggle('dark-theme', !isLight);
  const hljsTheme = document.getElementById('hljs-theme');
  if (hljsTheme) {
    hljsTheme.href = isLight ? 'vendor/hljs-light.min.css' : 'vendor/hljs-dark.min.css';
  }
}

// Initial theme from storage
const savedTheme = localStorage.getItem('forge_theme') || 'dark';
applyTheme(savedTheme);

window.addEventListener('storage', (e) => {
  if (e.key === 'forge_theme' && e.newValue) {
    applyTheme(e.newValue);
  }
  if (e.key === 'forge_active_session_id' && e.newValue && e.newValue !== currentSessionId) {
    // Rebind session if changed in main window
    rebindToSession(e.newValue);
  }
});

// ── Pan and Zoom ──────────────────────────────────────────────────────────────
function updateTreeTransform() {
  const layout = document.getElementById('tree-layout');
  if (layout) {
    layout.style.transform = `translate(${panX}px, ${panY}px) scale(${zoomScale})`;
  }
  if (zoomValueEl) {
    zoomValueEl.textContent = `${Math.round(zoomScale * 100)}%`;
  }
}

function zoom(delta, clientX = null, clientY = null) {
  const oldScale = zoomScale;
  zoomScale = Math.min(Math.max(0.25, zoomScale + delta), 3.0);

  if (clientX !== null && clientY !== null) {
    const rect = treeContainer.getBoundingClientRect();
    const mouseX = clientX - rect.left;
    const mouseY = clientY - rect.top;
    const layoutX = (mouseX - panX) / oldScale;
    const layoutY = (mouseY - panY) / oldScale;
    panX = mouseX - layoutX * zoomScale;
    panY = mouseY - layoutY * zoomScale;
  }
  updateTreeTransform();
  drawConnections();
}

function resetView() {
  panX = 60;
  panY = 60;
  zoomScale = 1.0;
  updateTreeTransform();
  drawConnections();
}

btnZoomIn.addEventListener('click', () => zoom(0.15));
btnZoomOut.addEventListener('click', () => zoom(-0.15));
btnZoomReset.addEventListener('click', resetView);

if (btnTreeBranchPrev) {
  btnTreeBranchPrev.addEventListener('click', () => {
    if (!currentActiveNodeId || currentActiveNodeId === 'node_root') return;
    const curr = currentNodes?.[currentActiveNodeId];
    if (curr?.parent_id) {
      socket.send(JSON.stringify({
        type: 'set_active',
        content: curr.parent_id
      }));
    }
  });
}

treeContainer.addEventListener('wheel', (e) => {
  e.preventDefault();
  zoom(e.deltaY * -0.001, e.clientX, e.clientY);
}, { passive: false });

treeContainer.addEventListener('mousedown', (e) => {
  if (e.target.closest('.node-btn') || e.target.closest('.tree-node-card')) {
    return;
  }
  isDragging = true;
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
  isDragging = false;
});

// ── Tree Rendering ────────────────────────────────────────────────────────────
function drawConnections() {
  const layout = document.getElementById('tree-layout');
  const svg = document.getElementById('tree-svg');
  if (!layout || !svg || !currentNodes) return;

  svg.innerHTML = '';
  svg.setAttribute('width', layout.scrollWidth);
  svg.setAttribute('height', layout.scrollHeight);

  const lRect = layout.getBoundingClientRect();

  const activePath = new Set();
  let curr = currentActiveNodeId;
  while (curr) {
    activePath.add(curr);
    const n = currentNodes[curr];
    curr = n ? n.parent_id : null;
  }

  Object.keys(currentNodes).forEach(nodeId => {
    const node = currentNodes[nodeId];
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

function renderTreeView(nodes, rootId, activeNodeId) {
  currentNodes = nodes;
  currentRootId = rootId;
  currentActiveNodeId = activeNodeId;

  if (btnTreeBranchPrev) {
    const canBranch = Boolean(activeNodeId && activeNodeId !== 'node_root' && nodes?.[activeNodeId]?.parent_id);
    btnTreeBranchPrev.disabled = !canBranch;
    btnTreeBranchPrev.style.opacity = canBranch ? '1' : '0.45';
  }

  // Preserve hint element
  const hintEl = treeContainer.querySelector('.canvas-hint');
  treeContainer.innerHTML = "";
  if (hintEl) treeContainer.appendChild(hintEl);

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
      if (newLabel !== null && socket && socket.readyState === WebSocket.OPEN) {
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
          if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({
              type: "undo",
              data: { node_id: nodeId }
            }));
          }
        }
      });
      actions.appendChild(undoBtn);
    }

    card.appendChild(actions);

    card.addEventListener('click', () => {
      if (nodeId !== activeNodeId && socket && socket.readyState === WebSocket.OPEN) {
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

  setTimeout(drawConnections, 60);

  if (currentResizeListener) {
    window.removeEventListener('resize', currentResizeListener);
  }
  currentResizeListener = drawConnections;
  window.addEventListener('resize', currentResizeListener);
}

// ── WebSocket Connection ──────────────────────────────────────────────────────
function connectWebSocket() {
  if (socket) {
    try { socket.close(); } catch (_) {}
  }

  const urlParams = new URLSearchParams(window.location.search);
  const requestedSession = urlParams.get('session_id') || localStorage.getItem('forge_active_session_id') || '';
  currentSessionId = requestedSession;

  const wsBase = (
    window.__FORGE_BACKEND_URL__ ||
    localStorage.getItem('forge_backend_url') ||
    'ws://localhost:8765'
  );
  const cleanWsBase = wsBase.replace(/\/ws\/?$/, '').replace(/\/$/, '');
  const wsUrl = `${cleanWsBase}/ws?role=secondary${requestedSession ? `&session_id=${encodeURIComponent(requestedSession)}` : ''}`;

  console.log('[tree] Connecting to backend:', wsUrl);
  socket = new WebSocket(wsUrl);

  socket.onopen = () => {
    console.log('[tree] WebSocket connected');
    statusDot.className = 'tree-status-dot online';
    statusDot.title = 'Connected to Forge backend';
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    // Fetch initial configuration (theme, etc.)
    socket.send(JSON.stringify({ type: 'get_config' }));
  };

  socket.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);

      if (msg.type === 'config') {
        if (msg.data && msg.data.THEME) {
          applyTheme(msg.data.THEME);
        }
      } else if (msg.type === 'tree_data') {
        if (msg.session_id) {
          currentSessionId = msg.session_id;
          sessionBadge.textContent = msg.session_id;
          sessionBadge.title = `Active Session: ${msg.session_id}`;
          localStorage.setItem('forge_active_session_id', msg.session_id);
        }
        renderTreeView(msg.nodes || {}, msg.root_id, msg.active_node_id);
      } else if (msg.type === 'session_switched') {
        if (msg.session_id) {
          currentSessionId = msg.session_id;
          sessionBadge.textContent = msg.session_id;
          sessionBadge.title = `Active Session: ${msg.session_id}`;
          localStorage.setItem('forge_active_session_id', msg.session_id);
        }
      }
    } catch (err) {
      console.error('[tree] Error parsing message:', err);
    }
  };

  socket.onerror = (err) => {
    console.warn('[tree] WebSocket error:', err);
    statusDot.className = 'tree-status-dot offline';
    statusDot.title = 'Connection error';
  };

  socket.onclose = () => {
    console.warn('[tree] WebSocket closed. Reconnecting in 2s...');
    statusDot.className = 'tree-status-dot offline';
    statusDot.title = 'Disconnected. Retrying...';
    if (!reconnectTimer) {
      reconnectTimer = setTimeout(connectWebSocket, 2000);
    }
  };
}

function rebindToSession(sessionId) {
  if (currentSessionId === sessionId) return;
  console.log('[tree] Switching session to:', sessionId);
  const url = new URL(window.location.href);
  url.searchParams.set('session_id', sessionId);
  window.history.replaceState({}, '', url.toString());
  connectWebSocket();
}

// Kick off connection
connectWebSocket();

