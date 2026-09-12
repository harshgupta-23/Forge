"""
app.py — WebSocket sidecar server
Wraps agent.py exactly as-is. Sets env vars from config BEFORE importing
agent so API_KEY / MODEL / AGENT_WORK_DIR are picked up at
module-load time (matching how agent.py was designed).
"""

import os
import sys
import json
import asyncio
import threading
import websockets
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
import pathlib

HOME = pathlib.Path.home()
# app.py lives in python_backend/, one level under the actual project root.
BACKEND_DIR  = pathlib.Path(__file__).parent
PROJECT_ROOT = BACKEND_DIR.parent
# config.json, sessions, scripts, the playwright browser, and pip-installed
# packages all live under the user's home profile — never inside the
# source/install tree — because the project folder may be inside
# Program Files (read-only for non-admins) once this is built into an MSI.
AGENT_HOME   = HOME / ".forge"
CONFIG_PATH  = AGENT_HOME / "config.json"
SESSION_DIR  = AGENT_HOME / "agent_sessions"
TOKEN_LOG_PATH = AGENT_HOME / "token_usage.log"
SCRIPTS_DIR  = AGENT_HOME / "agent_scripts"
PLAYWRIGHT_BROWSERS_DIR = AGENT_HOME / "playwright-browsers"
PIP_INSTALL_DIR         = AGENT_HOME / "python-packages"

# Create dirs on startup
AGENT_HOME.mkdir(parents=True, exist_ok=True)
SESSION_DIR.mkdir(parents=True, exist_ok=True)
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
PLAYWRIGHT_BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
PIP_INSTALL_DIR.mkdir(parents=True, exist_ok=True)

# Must be set/added before anything imports playwright or a runtime-installed
# package (including agent.py's tools), so the redirection actually takes effect.
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_DIR)
sys.path.insert(0, str(PIP_INSTALL_DIR))

_existing_pypath = os.environ.get("PYTHONPATH", "")
os.environ["PYTHONPATH"] = str(PIP_INSTALL_DIR) + (os.pathsep + _existing_pypath if _existing_pypath else "")

# ─── Config helpers ───────────────────────────────────────────────────────────

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        # First run — copy template from app bundle
        template = PROJECT_ROOT / "config.template.json"
        if template.exists():
            import shutil
            shutil.copy(template, CONFIG_PATH)
        else:
            # Fallback defaults
            save_config({
                "API_KEY": "",
                "MODEL": "gemma-4-26b-a4b-it",
                "API_BASE": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "AGENT_WORK_DIR": str(AGENT_HOME / "agent_outputs"),
                "THEME": "dark"
            })
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(data: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)

def apply_config_to_env(cfg: dict) -> None:
    # Always write every key that's present in cfg, even if blank.
    # Skipping blank values meant a cleared field in the UI would leave the
    # old env var (and old API key) silently in place.
    for key in ("API_KEY", "MODEL", "API_BASE", "AGENT_WORK_DIR"):
        if key in cfg:
            os.environ[key] = cfg[key]

# ─── Apply config BEFORE importing agent ──────────────────────────────────────

apply_config_to_env(load_config())

def _ensure_playwright_chromium() -> None:
    """
    The installer ships without a bundled browser (chosen to keep the MSI
    small). On first run — and only on first run — download Chromium into
    PLAYWRIGHT_BROWSERS_DIR. Runs in a background thread so server startup
    isn't blocked; browser_action will simply fail with Playwright's normal
    "executable doesn't exist" error if a user tries it before this finishes.
    """
    marker = PLAYWRIGHT_BROWSERS_DIR / ".chromium_installed"
    if marker.exists():
        return
    try:
        import subprocess, sys
        print("[app] First run: downloading Chromium for browser_action...")
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
        marker.touch()
        print("[app] Chromium download complete.")
    except Exception as exc:
        print(f"[app] Chromium download failed, will retry next launch: {exc}")

threading.Thread(target=_ensure_playwright_chromium, daemon=True).start()

from langchain_core.messages import HumanMessage
from agent import stream_final_response, count_tokens, summarise_history

# ─── Session directory setup ──────────────────────────────────────────────────

os.makedirs(SESSION_DIR, exist_ok=True)

# ─── Per-connection state (Branching Tree) ───────────────────────────────────

import uuid
import glob
from datetime import datetime, timezone
from langchain_core.messages import AIMessage, ToolMessage

def serialize_message(msg):
    if isinstance(msg, HumanMessage):
        return {"type": "human", "content": msg.content}
    elif isinstance(msg, AIMessage):
        return {"type": "ai", "content": msg.content}
    elif isinstance(msg, ToolMessage):
        return {
            "type": "tool",
            "content": msg.content,
            "name": getattr(msg, "name", "tool"),
            "tool_call_id": getattr(msg, "tool_call_id", "tool")
        }
    return None

def deserialize_message(d):
    t = d.get("type")
    if t == "human":
        return HumanMessage(content=d["content"])
    elif t == "ai":
        return AIMessage(content=d["content"])
    elif t == "tool":
        return ToolMessage(
            content=d["content"],
            name=d.get("name", "tool"),
            tool_call_id=d.get("tool_call_id", "tool")
        )
    return None

def extract_tool_calls_and_results(intermediate_msgs):
    tool_calls = []
    tool_results = []
    for msg in intermediate_msgs:
        if isinstance(msg, AIMessage):
            from agent import _parse_tools
            calls = _parse_tools(msg.content)
            if calls:
                tool_calls.extend(calls)
        elif isinstance(msg, ToolMessage):
            tool_results.append({
                "name": getattr(msg, "name", "tool"),
                "content": msg.content,
                "summary": msg.content.split('\n')[0][:80] if msg.content else ""
            })
    return tool_calls, tool_results

class ConversationTree:
    def __init__(self, session_id=None, label=None):
        self.session_id = session_id or f"sess_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.root_id = "node_root"
        self.active_node_id = "node_root"
        self.label = label
        self.nodes = {
            "node_root": {
                "id": "node_root",
                "parent_id": None,
                "children_ids": [],
                "created_at": self.created_at,
                "type": "root",
                "user_message": None,
                "agent_message": None,
                "tool_calls": [],
                "label": None,
                "intermediate_messages": []
            }
        }

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "root_id": self.root_id,
            "active_node_id": self.active_node_id,
            "label": self.label,
            "nodes": self.nodes
        }

    @classmethod
    def from_dict(cls, d):
        tree = cls()
        tree.session_id = d.get("session_id", tree.session_id)
        tree.created_at = d.get("created_at", tree.created_at)
        tree.root_id = d.get("root_id", "node_root")
        tree.active_node_id = d.get("active_node_id", "node_root")
        tree.label = d.get("label")
        tree.nodes = d.get("nodes", tree.nodes)
        return tree

    def get_path(self, node_id) -> list:
        path = []
        curr_id = node_id
        while curr_id:
            node = self.nodes.get(curr_id)
            if not node:
                break
            path.append(node)
            if node.get("type") == "summary":
                break
            curr_id = node.get("parent_id")
        path.reverse()
        return path

    def get_active_path_messages(self) -> list:
        path = self.get_path(self.active_node_id)
        messages = []
        for node in path:
            if node.get("type") == "root":
                continue
            
            # 1. User message
            user_msg_dict = node.get("user_message")
            if user_msg_dict:
                messages.append(HumanMessage(content=user_msg_dict.get("content", "")))
            
            # 2. Intermediate messages
            inter_msgs_dicts = node.get("intermediate_messages", [])
            for m_dict in inter_msgs_dicts:
                msg = deserialize_message(m_dict)
                if msg:
                    messages.append(msg)
            
            # 3. Final agent message
            agent_msg_dict = node.get("agent_message")
            if agent_msg_dict:
                messages.append(AIMessage(content=agent_msg_dict.get("content", "")))
        return messages

    def create_node(self, parent_id, user_msg, intermediate_msgs, final_msg, label=None, node_type="turn") -> str:
        node_id = f"node_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:4]}"
        
        user_message_dict = None
        if user_msg:
            user_message_dict = {
                "role": "user",
                "content": user_msg.content,
                "attachments": []
            }
            
        agent_message_dict = None
        tool_calls = []
        tool_results = []
        if final_msg:
            tool_calls, tool_results = extract_tool_calls_and_results(intermediate_msgs)
            agent_message_dict = {
                "role": "assistant",
                "content": final_msg.content,
                "tool_calls": tool_calls,
                "tool_results": tool_results
            }
            
        intermediate_serialized = [serialize_message(m) for m in intermediate_msgs]
        
        node = {
            "id": node_id,
            "parent_id": parent_id,
            "children_ids": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "type": node_type,
            "user_message": user_message_dict,
            "agent_message": agent_message_dict,
            "tool_calls": tool_calls,
            "label": label,
            "intermediate_messages": intermediate_serialized
        }
        
        self.nodes[node_id] = node
        
        if parent_id and parent_id in self.nodes:
            if node_id not in self.nodes[parent_id]["children_ids"]:
                self.nodes[parent_id]["children_ids"].append(node_id)
                
        self.active_node_id = node_id
        return node_id

    def undo(self) -> str:
        active_node = self.nodes.get(self.active_node_id)
        if active_node and active_node.get("parent_id"):
            self.active_node_id = active_node["parent_id"]
            return self.active_node_id
        return self.active_node_id

    def save_tree(self, filepath):
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
        except Exception as exc:
            print(f"[app] Error saving session tree: {exc}")

def load_or_create_tree(session_dir) -> ConversationTree:
    """Always create a fresh tree for each new connection.

    Previously this auto-loaded the most recently modified session file,
    causing every new app launch to resume the old session.  Sessions are
    now ephemeral per-connection; they are persisted to disk so the tree
    panel stays consistent *within* a session, but are never reloaded
    automatically on reconnect.
    """
    tree = ConversationTree()
    filepath = os.path.join(session_dir, f"session_{tree.session_id}.json")
    tree.save_tree(filepath)
    print(f"[app] Created fresh session tree at {filepath}")
    return tree

class Session:
    def __init__(self):
        self.tree = load_or_create_tree(SESSION_DIR)
        self.attached_files: dict = {}
        self.stop_event = None
        self.generation_task = None

# Helper to send updated chat and tree to frontend
async def send_chat_and_tree(websocket, session: Session):
    path_msgs = session.tree.get_active_path_messages()
    serialized_path = []
    for m in path_msgs:
        ser = serialize_message(m)
        if ser:
            serialized_path.append(ser)
        
    await websocket.send(json.dumps({
        "type": "chat_history",
        "messages": serialized_path,
        "active_node_id": session.tree.active_node_id
    }))
    
    await websocket.send(json.dumps({
        "type": "tree_data",
        "session_id": session.tree.session_id,
        "root_id": session.tree.root_id,
        "active_node_id": session.tree.active_node_id,
        "nodes": session.tree.nodes
    }))

def list_available_sessions() -> list:
    """Scan SESSION_DIR for saved trees and return lightweight summaries
    (used by the 'Fetch Previous Session' picker). Skips empty sessions
    that only contain the root node."""
    sessions = []
    for filepath in glob.glob(os.path.join(SESSION_DIR, "session_*.json")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        nodes = d.get("nodes", {})
        if len(nodes) <= 1:
            continue  # root-only, nothing worth resuming
        preview = ""
        for node in nodes.values():
            if node.get("type") != "root" and node.get("user_message"):
                preview = node["user_message"].get("content", "")[:60]
                break
        sessions.append({
            "session_id": d.get("session_id"),
            "created_at": d.get("created_at"),
            "node_count": len(nodes),
            "preview": preview,
            "label": d.get("label"),
        })
    sessions.sort(key=lambda s: s.get("created_at") or "", reverse=True)
    return sessions

def log_token_usage(tokens: int) -> None:
    """Append one JSON-line record per completed turn. Each line represents
    the full context-token count for that turn (since every API call resends
    the whole conversation), used as an approximation of usage over time."""
    try:
        with open(TOKEN_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "tokens": tokens}) + "\n")
    except Exception as exc:
        print(f"[app] Could not log token usage: {exc}")

def get_token_usage_windows() -> dict:
    now = datetime.now(timezone.utc)
    last_5h = 0
    last_24h = 0
    if TOKEN_LOG_PATH.exists():
        try:
            with open(TOKEN_LOG_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        ts = datetime.fromisoformat(entry["ts"])
                        tokens = int(entry.get("tokens", 0))
                    except Exception:
                        continue
                    age_hours = (now - ts).total_seconds() / 3600
                    if age_hours <= 24:
                        last_24h += tokens
                        if age_hours <= 5:
                            last_5h += tokens
        except Exception as exc:
            print(f"[app] Could not read token usage log: {exc}")
    return {"last_5h": last_5h, "last_24h": last_24h}

# ─── Connection tracking and delayed shutdown ──────────────────────────────────
active_connections = 0
shutdown_task = None

async def delayed_shutdown(delay_seconds):
    await asyncio.sleep(delay_seconds)
    print(f"[app] No clients connected for {delay_seconds} seconds. Shutting down...")
    sys.stdout.flush()
    os.system('taskkill /F /PID {} /T >nul 2>&1'.format(os.getpid()))

# ─── WebSocket handler ────────────────────────────────────────────────────────

async def handler(websocket):
    global active_connections, shutdown_task
    active_connections += 1
    if shutdown_task and not shutdown_task.done():
        shutdown_task.cancel()
        print("[app] Client connected. Cancelled pending shutdown.")
        sys.stdout.flush()

    session = Session()

    try:
        async for raw_message in websocket:
            event = json.loads(raw_message)
            ev_type = event.get("type")

            # ── get_config ────────────────────────────────────────────────────
            if ev_type == "get_config":
                await websocket.send(json.dumps({
                    "type": "config",
                    "data": load_config(),
                }))
                await send_chat_and_tree(websocket, session)

            # ── save_config ───────────────────────────────────────────────────
            elif ev_type == "save_config":
                cfg = event.get("data", {})
                save_config(cfg)
                apply_config_to_env(cfg)
                # No module reload needed — agent._get_client() reads os.environ
                # at call time, so updated values are picked up immediately.
                # importlib.reload() was previously used here but caused the
                # stale-import bug: functions already bound from 'from agent import …'
                # would keep referencing the old module's closure.
                await websocket.send(json.dumps({
                    "type": "status",
                    "content": "Configuration saved and applied.",
                }))

            # ── save_session ──────────────────────────────────────────────────
            elif ev_type == "save_session":
                filename = f"session_{session.tree.session_id}.txt"
                client_content = event.get("content", "")   # header from JS (timestamps, tokens)
                full_path = os.path.join(SESSION_DIR, filename)
                try:
                    log_lines = []
                    path_msgs = session.tree.get_active_path_messages()
                    for m in path_msgs:
                        if isinstance(m, HumanMessage):
                            log_lines.append(f"[You] {m.content}")
                        elif isinstance(m, AIMessage):
                            log_lines.append(f"[Agent] {m.content}")
                        elif isinstance(m, ToolMessage):
                            log_lines.append(f"[Tool:{getattr(m,'name','?')}] {m.content}")
                    
                    final_content = client_content + "\n".join(log_lines)
                    
                    with open(full_path, "w", encoding="utf-8") as f:
                        f.write(final_content)
                    await websocket.send(json.dumps({
                        "type": "status",
                        "content": f"Session saved → {full_path}",
                    }))
                except Exception as exc:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "content": f"Could not save session: {exc}",
                    }))
            # ── list_sessions ────────────────────────────────────────────────
            elif ev_type == "list_sessions":
                await websocket.send(json.dumps({
                    "type": "session_list",
                    "sessions": list_available_sessions(),
                }))

            # ── load_session ─────────────────────────────────────────────────
            elif ev_type == "load_session":
                target_id = (event.get("data") or {}).get("session_id") or event.get("content")
                filepath = os.path.join(SESSION_DIR, f"session_{target_id}.json")
                if not target_id or not os.path.exists(filepath):
                    await websocket.send(json.dumps({
                        "type": "error",
                        "content": f"Session not found: {target_id}",
                    }))
                else:
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            loaded_dict = json.load(f)
                        # Swapping in the loaded tree wholesale carries its
                        # session_id along too, so every future save_tree()/
                        # save_session write keeps landing on this SAME
                        # json/txt pair — as if there was no interruption.
                        session.tree = ConversationTree.from_dict(loaded_dict)
                        await websocket.send(json.dumps({
                            "type": "status",
                            "content": f"Resumed previous session ({session.tree.session_id}).",
                        }))
                        await send_chat_and_tree(websocket, session)
                    except Exception as exc:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "content": f"Could not load session: {exc}",
                        }))

            # ── get_token_usage ──────────────────────────────────────────────
            elif ev_type == "get_token_usage":
                await websocket.send(json.dumps({
                    "type": "token_usage_windows",
                    **get_token_usage_windows(),
                }))
                
            # ── shutdown ──────────────────────────────────────────────────────────
            elif ev_type == "shutdown":
                print("[app] Shutdown requested by client. Exiting.")
                sys.stdout.flush()
                os.system('taskkill /F /PID {} /T >nul 2>&1'.format(os.getpid()))

            # ── attach_file ───────────────────────────────────────────────────
            elif ev_type == "attach_file":
                name = event.get("name", "")
                path = event.get("path", "")
                if name and path:
                    session.attached_files[name] = path
                    await websocket.send(json.dumps({
                        "type": "status",
                        "content": f"File attached: {name}",
                    }))

            # ── clear ─────────────────────────────────────────────────────────
            elif ev_type == "clear":
                session.tree = ConversationTree()
                session.tree.save_tree(os.path.join(SESSION_DIR, f"session_{session.tree.session_id}.json"))
                await websocket.send(json.dumps({
                    "type": "status",
                    "content": "History cleared (started a new session).",
                }))
                await send_chat_and_tree(websocket, session)

            # ── undo ──────────────────────────────────────────────────────────────────
            elif ev_type == "undo":
                active_node = session.tree.nodes.get(session.tree.active_node_id)
                if active_node and active_node.get("parent_id"):
                    session.tree.undo()
                    session.tree.save_tree(os.path.join(SESSION_DIR, f"session_{session.tree.session_id}.json"))
                    await websocket.send(json.dumps({
                        "type": "status",
                        "content": "Undone: moved to parent branch.",
                    }))
                    await send_chat_and_tree(websocket, session)
                else:
                    await websocket.send(json.dumps({
                        "type": "status",
                        "content": "Nothing to undo.",
                    }))

            # ── stop_generation ──────────────────────────────────────────────
            elif ev_type == "stop_generation":
                if session.stop_event and not session.stop_event.is_set():
                    session.stop_event.set()
                    await websocket.send(json.dumps({
                        "type": "status",
                        "content": "Stopping generation…",
                    }))
                else:
                    await websocket.send(json.dumps({
                        "type": "status",
                        "content": "Nothing to stop.",
                    }))
            
            # ── summarise ─────────────────────────────────────────────────────
            elif ev_type == "summarise":
                active_path_msgs = session.tree.get_active_path_messages()
                path_nodes = session.tree.get_path(session.tree.active_node_id)
                content_nodes = [n for n in path_nodes if n.get("type") != "root"]
                
                if len(content_nodes) <= 2:
                    await websocket.send(json.dumps({
                        "type": "status",
                        "content": "Conversation path too short to summarise.",
                    }))
                else:
                    before = count_tokens(active_path_msgs)
                    loop = asyncio.get_event_loop()
                    compressed_msgs = await loop.run_in_executor(
                        None,
                        summarise_history,
                        active_path_msgs,
                        session.attached_files,
                    )
                    after = count_tokens(compressed_msgs)
                    summary_text = compressed_msgs[1].content if len(compressed_msgs) > 1 else ""
                    
                    summary_user = compressed_msgs[0]
                    summary_agent = compressed_msgs[1]
                    
                    summary_node_id = session.tree.create_node(
                        parent_id=session.tree.root_id,
                        user_msg=summary_user,
                        intermediate_msgs=[],
                        final_msg=summary_agent,
                        node_type="summary",
                        label=f"Summary of {len(content_nodes) - 2} turns"
                    )
                    
                    last_2_nodes = content_nodes[-2:]
                    current_parent = summary_node_id
                    for node in last_2_nodes:
                        node_user_dict = node.get("user_message")
                        node_user = HumanMessage(content=node_user_dict["content"]) if node_user_dict else None
                        
                        node_inter_dicts = node.get("intermediate_messages", [])
                        node_inter = [deserialize_message(d) for d in node_inter_dicts]
                        
                        node_agent_dict = node.get("agent_message")
                        node_agent = AIMessage(content=node_agent_dict["content"]) if node_agent_dict else None
                        
                        current_parent = session.tree.create_node(
                            parent_id=current_parent,
                            user_msg=node_user,
                            intermediate_msgs=node_inter,
                            final_msg=node_agent,
                            node_type=node.get("type", "turn"),
                            label=node.get("label")
                        )
                    
                    session.tree.active_node_id = current_parent
                    session.tree.save_tree(os.path.join(SESSION_DIR, f"session_{session.tree.session_id}.json"))
                    
                    await websocket.send(json.dumps({
                        "type": "status",
                        "content": f"History compressed: {before:,} → {after:,} tokens.",
                    }))
                    await websocket.send(json.dumps({
                        "type": "summarised",
                        "content": summary_text or "Summary complete.",
                    }))
                    await send_chat_and_tree(websocket, session)

            # ── user_message ──────────────────────────────────────────────────
            elif ev_type == "user_message":
                user_text = event.get("content", "").strip()
                if not user_text:
                    continue

                if session.generation_task and not session.generation_task.done():
                    await websocket.send(json.dumps({
                        "type": "status",
                        "content": "Already generating — stop it first or wait for it to finish.",
                    }))
                    continue

                cfg = load_config()
                if not cfg.get("API_KEY"):
                    await websocket.send(json.dumps({
                        "type": "error",
                        "content": "API_KEY is not set. Open Settings and add your key.",
                    }))
                    await websocket.send(json.dumps({"type": "done"}))
                    continue

                prior_msgs = session.tree.get_active_path_messages()
                user_msg = HumanMessage(content=user_text)
                state = {
                    "messages": prior_msgs + [user_msg],
                    "attached_files": session.attached_files,
                }

                session.stop_event = threading.Event()

                async def _generate(state=state, prior_len=len(prior_msgs)):
                    try:
                        await _run_stream(websocket, state, session, prior_len)
                    except Exception as exc:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "content": str(exc),
                        }))
                        await websocket.send(json.dumps({"type": "done"}))

                # IMPORTANT: do not `await` this directly. `async for raw_message
                # in websocket` only reads the next message once the current
                # iteration's body finishes — awaiting generation here would
                # block the loop from ever seeing a "stop_generation" message
                # until generation had already finished on its own, making
                # Stop a no-op for anything still in progress (thinking,
                # streaming, or running tools).
                session.generation_task = asyncio.create_task(_generate())

            # ── set_active ────────────────────────────────────────────────────
            elif ev_type == "set_active":
                node_id = event.get("content") or event.get("data")
                if node_id in session.tree.nodes:
                    session.tree.active_node_id = node_id
                    session.tree.save_tree(os.path.join(SESSION_DIR, f"session_{session.tree.session_id}.json"))
                    await websocket.send(json.dumps({
                        "type": "status",
                        "content": f"Switched active node.",
                    }))
                    await send_chat_and_tree(websocket, session)
                else:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "content": f"Node {node_id} not found in tree.",
                    }))

            # ── set_label ─────────────────────────────────────────────────────
            elif ev_type == "set_label":
                data = event.get("data") or {}
                node_id = data.get("node_id")
                label = data.get("label")
                if node_id in session.tree.nodes:
                    session.tree.nodes[node_id]["label"] = label or None
                    session.tree.save_tree(os.path.join(SESSION_DIR, f"session_{session.tree.session_id}.json"))
                    await websocket.send(json.dumps({
                        "type": "status",
                        "content": "Updated node label.",
                    }))
                    await send_chat_and_tree(websocket, session)
                else:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "content": f"Node {node_id} not found.",
                    }))
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if session.generation_task and not session.generation_task.done():
            session.generation_task.cancel()
        active_connections -= 1
        print(f"[app] Client disconnected. Remaining active connections: {active_connections}")
        sys.stdout.flush()
        if active_connections == 0:
            shutdown_task = asyncio.create_task(delayed_shutdown(5))


async def _run_stream(websocket, state: dict, session: Session, prior_messages_len: int):
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _producer():
        try:
            from agent import stream_final_response
            for event_type, payload in stream_final_response(state, stop_event=session.stop_event):
                if event_type == "done":
                    asyncio.run_coroutine_threadsafe(
                        queue.put(("done", payload)), loop
                    ).result()
                else:
                    asyncio.run_coroutine_threadsafe(
                        queue.put((event_type, payload)), loop
                    ).result()
        except Exception as exc:
            asyncio.run_coroutine_threadsafe(
                queue.put(("error", str(exc))), loop
            ).result()
        finally:
            asyncio.run_coroutine_threadsafe(
                queue.put(("__end__", None)), loop
            ).result()

    thread = threading.Thread(target=_producer, daemon=True)
    thread.start()

    while True:
        event_type, payload = await queue.get()

        if event_type == "__end__":
            await websocket.send(json.dumps({"type": "done"}))
            break

        elif event_type in ("done", "cancelled"):
            new_msgs = payload[prior_messages_len:]
            if len(new_msgs) >= 2:
                user_msg = new_msgs[0]
                inter_msgs = new_msgs[1:-1]
                final_msg = new_msgs[-1]
            elif len(new_msgs) == 1:
                user_msg = new_msgs[0]
                inter_msgs = []
                final_msg = AIMessage(content="[No response]")
            else:
                user_msg = HumanMessage(content="[Empty]")
                inter_msgs = []
                final_msg = AIMessage(content="[No response]")
                
            session.tree.create_node(
                parent_id=session.tree.active_node_id,
                user_msg=user_msg,
                intermediate_msgs=inter_msgs,
                final_msg=final_msg
            )
            session.tree.save_tree(os.path.join(SESSION_DIR, f"session_{session.tree.session_id}.json"))
            
            active_path_msgs = session.tree.get_active_path_messages()
            tokens = count_tokens(active_path_msgs)
            await websocket.send(json.dumps({
                "type": "token_count",
                "content": tokens,
            }))

            log_token_usage(tokens)
            await websocket.send(json.dumps({
                "type": "token_usage_windows",
                **get_token_usage_windows(),
            }))
            if event_type == "cancelled":
                await websocket.send(json.dumps({
                    "type": "status",
                    "content": "Generation stopped by user.",
                }))

            await send_chat_and_tree(websocket, session)

        elif event_type == "error":
            await websocket.send(json.dumps({
                "type": "error",
                "content": payload,
            }))

        else:
            clean = _strip_ansi(str(payload))
            await websocket.send(json.dumps({
                "type": event_type,
                "content": clean,
            }))


# ─── ANSI stripper ────────────────────────────────────────────────────────────

import re as _re
_ANSI_RE = _re.compile(r'\x1b\[[0-9;]*[mKJ]|\r')

def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main():
    print(f"Python Agent Sidecar initialised on ws://localhost:8765")
    print(f"Sessions will be saved to: {SESSION_DIR}")
    async with websockets.serve(handler, "localhost", 8765):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())