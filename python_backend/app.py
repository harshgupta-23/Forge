"""
app.py — WebSocket sidecar server
Wraps agent.py exactly as-is. Sets env vars from config BEFORE importing
agent so GEMINI_API_KEY / GEMINI_MODEL / AGENT_WORK_DIR are picked up at
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
CONFIG_PATH  = HOME / ".myagent" / "config.json"
SESSION_DIR  = HOME / ".myagent" / "agent_sessions"
SCRIPTS_DIR  = HOME / ".agent_scripts"
# Embedded Python lives under Program Files, which standard (non-admin)
# users can't write to. Playwright's browser binaries must be cached
# somewhere writable, so we redirect them into the user's profile.
PLAYWRIGHT_BROWSERS_DIR = HOME / ".myagent" / "playwright-browsers"
# Same problem applies to packages the agent installs at runtime via the
# pip_install tool — the embedded interpreter's own site-packages is
# read-only post-install. Packages always go here instead, and this
# directory is added to sys.path below so they're importable immediately.
PIP_INSTALL_DIR = HOME / ".myagent" / "python-packages"

# Create dirs on startup
CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
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
        template = pathlib.Path(__file__).parent.parent / "config.template.json"
        if template.exists():
            import shutil
            shutil.copy(template, CONFIG_PATH)
        else:
            # Fallback defaults
            save_config({
                "GEMINI_API_KEY": "",
                "GEMINI_MODEL": "gemma-4-26b-a4b-it",
                "GEMINI_API_BASE": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "AGENT_WORK_DIR": str(HOME / "agent_outputs"),
                "THEME": "dark"
            })
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(data: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)

def apply_config_to_env(cfg: dict) -> None:
    for key in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_API_BASE", "AGENT_WORK_DIR"):
        if cfg.get(key):
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

# ─── Per-connection state ─────────────────────────────────────────────────────

class Session:
    def __init__(self):
        self.history: list = []          # active — passed to LLM, modified by clear/undo/summarise
        self.full_log: list = []         # permanent — only appended to, never deleted, saved to txt
        self.attached_files: dict = {}


# ─── WebSocket handler ────────────────────────────────────────────────────────

async def handler(websocket):
    session = Session()

    async for raw_message in websocket:
        event = json.loads(raw_message)
        ev_type = event.get("type")

        # ── get_config ────────────────────────────────────────────────────
        if ev_type == "get_config":
            await websocket.send(json.dumps({
                "type": "config",
                "data": load_config(),
            }))

        # ── save_config ───────────────────────────────────────────────────
        elif ev_type == "save_config":
            cfg = event.get("data", {})
            save_config(cfg)
            apply_config_to_env(cfg)
            import importlib, agent as _agent_mod
            importlib.reload(_agent_mod)
            await websocket.send(json.dumps({
                "type": "status",
                "content": "Configuration saved and applied.",
            }))

        # ── save_session ──────────────────────────────────────────────────
        elif ev_type == "save_session":
            filename  = event.get("filename", "session.txt")
            client_content = event.get("content", "")   # header from JS (timestamps, tokens)
            safe_name = os.path.basename(filename)
            full_path = os.path.join(SESSION_DIR, safe_name)
            try:
                # Build log from full_log instead of JS-rendered text
                log_lines = []
                for m in session.full_log:
                    if isinstance(m, HumanMessage):
                        log_lines.append(f"[You] {m.content}")
                    elif isinstance(m, AIMessage):
                        log_lines.append(f"[Agent] {m.content}")
                    elif isinstance(m, ToolMessage):
                        log_lines.append(f"[Tool:{getattr(m,'name','?')}] {m.content}")
                
                # client_content has the header (timestamps, token count)
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

        # ── shutdown ──────────────────────────────────────────────────────────
        elif ev_type == "shutdown":
            print("[app] Shutdown requested by client. Exiting.")
            import sys
            sys.stdout.flush()
            os.system('taskkill /F /PID {} /T'.format(os.getpid()))

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
            session.history.clear()
            session.full_log.append(HumanMessage(content="**cleared chat history**"))
            await websocket.send(json.dumps({
                "type": "status",
                "content": "History cleared.",
            }))

        # ── undo ──────────────────────────────────────────────────────────────────
        elif ev_type == "undo":
            # Remove last 2 messages (1 user + 1 assistant turn)
            if len(session.history) >= 2:
                session.history = session.history[:-2]
                session.full_log.append(HumanMessage(content="**undo chat history (1 user assistant turn)**"))
                await websocket.send(json.dumps({
                    "type": "status",
                    "content": "Last turn removed from history.",
                }))
            else:
                await websocket.send(json.dumps({
                    "type": "status",
                    "content": "Nothing to undo.",
                }))
        
        # ── summarise ─────────────────────────────────────────────────────
        elif ev_type == "summarise":
            if len(session.history) <= 4:
                await websocket.send(json.dumps({
                    "type": "status",
                    "content": "History too short to summarise.",
                }))
            else:
                before = count_tokens(session.history)
                loop = asyncio.get_event_loop()
                session.history = await loop.run_in_executor(
                    None,
                    summarise_history,
                    session.history,
                    session.attached_files,
                )
                after = count_tokens(session.history)
                summary_text = session.history[1].content if len(session.history) > 1 else ""
                session.full_log.append(HumanMessage(content="**history summarised by user**"))
                session.full_log.append(AIMessage(content=f"[Summary]\n{summary_text}"))
                await websocket.send(json.dumps({
                    "type": "status",
                    "content": f"History compressed: {before:,} → {after:,} tokens.",
                }))
                await websocket.send(json.dumps({
                    "type": "summarised",
                    "content": summary_text or "Summary complete.",
                }))

        # ── user_message ──────────────────────────────────────────────────
        elif ev_type == "user_message":
            user_text = event.get("content", "").strip()
            if not user_text:
                continue

            cfg = load_config()
            if not cfg.get("GEMINI_API_KEY"):
                await websocket.send(json.dumps({
                    "type": "error",
                    "content": "GEMINI_API_KEY is not set. Open Settings and add your key.",
                }))
                await websocket.send(json.dumps({"type": "done"}))
                continue

            msg = HumanMessage(content=user_text)
            session.history.append(msg)
            session.full_log.append(msg) 
            state = {
                "messages": session.history,
                "attached_files": session.attached_files,
            }

            try:
                await _run_stream(websocket, state, session)
            except Exception as exc:
                await websocket.send(json.dumps({
                    "type": "error",
                    "content": str(exc),
                }))
                await websocket.send(json.dumps({"type": "done"}))


async def _run_stream(websocket, state: dict, session: Session):
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _producer():
        try:
            from agent import stream_final_response
            for event_type, payload in stream_final_response(state):
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

        elif event_type == "done":
            new_msgs = payload[len(session.history):]
            session.history = payload
            for m in new_msgs:
                session.full_log.append(m) 
            tokens = count_tokens(session.history)
            await websocket.send(json.dumps({
                "type": "token_count",
                "content": tokens,
            }))

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